#!/usr/bin/env python3
"""
Vision LLM Classifier using Qwen Code (qw2) CLI
Классифицирует CAPTCHA плитки с помощью консольного qw2

Два способа использования:
1. Python SDK: from qwen_code_sdk import query
2. CLI: qwen <prompt>
"""
import asyncio
import base64
import json
import os
import signal
import tempfile
import uuid
from pathlib import Path
from typing import List, Dict, Any
import subprocess

# Try to import Qwen Code SDK
try:
    from qwen_code_sdk import query, is_sdk_result_message
    HAS_QWEN_SDK = True
except ImportError:
    HAS_QWEN_SDK = False
    print("⚠️ qwen_code_sdk not installed. Install with: pip install qwen-code-sdk")


# The analysed image (and the instruction that comes with it) is content from a
# page the attacker controls, so it must reach the model as data only. `qwen`
# registers a handful of tools even in headless mode, and `tool_call` is a door
# to everything else (agent, web_fetch, cron_*), so the deferred tools are
# excluded by name too. With --core-tools structured_output plus this list the
# request carries exactly one tool: the JSON-schema answer.
EXCLUDED_TOOLS = [
    "skill",
    "tool_call",
    "tool_search",
    "agent",
    "get_goal",
    "update_goal",
    "report_findings",
    "enter_worktree",
    "exit_worktree",
    "record_artifact",
    "list_agents",
    "send_message",
    "task_stop",
]


# Seconds to wait for a killed qwen CLI to be reaped. `Process.wait()` also
# waits for the stdout/stderr pipes to close, so a grandchild that inherited
# them could otherwise hang the worker forever after `kill()`.
_REAP_TIMEOUT = 5.0


async def _reap(process) -> None:
    """Kill the qwen CLI with its whole process group, then reap it, bounded."""
    pid = getattr(process, "pid", None)
    # Kill the group also when asyncio has already reaped the leader: the CLI
    # exits before the descendant that inherited its stdout/stderr, and that
    # descendant is precisely what has to die. The leader's PID is the group
    # ID, and Linux does not hand a PID to a new process while any process
    # still uses it as PGID/SID, so while the group holds a process the number
    # is ours. Once the group is empty and reaped the number is free again:
    # usually `killpg` then raises ProcessLookupError (caught below), but if
    # PID allocation wrapped past `pid_max` in that gap and a new group leader
    # got the number, SIGKILL would hit that group. Tiny window, but not zero.
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.kill()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=_REAP_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"⚠️ qwen process not reaped within {_REAP_TIMEOUT}s", flush=True)


def _answer_summary(result) -> str:
    """Safe log line for a model answer: the tile count only, never its text.

    The answer (and any reasoning the model puts next to it) is shaped by an
    attacker-controlled image, so it stays out of the log.
    """
    indices = result.get("indices") if isinstance(result, dict) else None
    if isinstance(indices, list):
        return f"{len(indices)} tile(s) selected"
    return "no tile list"


class VisionLLMClassifier:
    """Классификатор CAPTCHA с использованием qw2 CLI"""

    def __init__(self):
        from app.config import settings
        
        self.temp_dir = Path(tempfile.mkdtemp(prefix="captcha_vision_"))
        self.vision_model = settings.vision_model
        self.api_key = settings.bailian_api_key or os.environ.get("BAILIAN_CODING_PLAN_API_KEY")
        
        # Check if Vision LLM is available
        if not self.api_key:
            print("⚠️ Vision LLM disabled: BAILIAN_CODING_PLAN_API_KEY not set")
            print("   Hybrid classifier will use YOLO only")
            self.enabled = False
        else:
            print(f"✅ Vision LLM enabled: model={self.vision_model}")
            self.enabled = True

    async def classify_tiles(
        self,
        image_bytes: bytes,
        instruction: str,
        grid_size: str = "3x3"
    ) -> List[int]:
        """
        Классифицирует CAPTCHA плитки

        Args:
            image_bytes: Изображение CAPTCHA (PNG/JPEG)
            instruction: Инструкция (например, "Select all bicycles")
            grid_size: Размер сетки ("3x3", "4x4", "2x3")

        Returns:
            Список индексов плиток для клика (например, [0, 3, 6])
        """
        # Check if Vision LLM is enabled
        if not self.enabled:
            raise RuntimeError("Vision LLM is disabled (no API key)")
        
        # 1. Сохраняем изображение во временный файл с уникальным именем
        unique_id = str(uuid.uuid4())[:8]
        image_path = self.temp_dir / f"captcha_{unique_id}.png"
        try:
            with open(image_path, "wb") as f:
                f.write(image_bytes)

            # 2. Формируем prompt для qw2
            prompt = self._build_prompt(instruction, grid_size)

            # 3. Вызываем qw2 для классификации
            result = await self._call_qwen_cli(image_path, prompt)

            # 4. Парсим результат
            return self._parse_response(result)
        finally:
            # Картинка и инструкция пришли со страницы, которую контролирует
            # атакующий: не оставлять их на диске ни при успехе, ни при
            # падении/таймауте (иначе /tmp воркера копится чужим контентом).
            image_path.unlink(missing_ok=True)

    def _build_prompt(self, instruction: str, grid_size: str) -> str:
        """Создает prompt для vision model"""

        grid_info = {
            "3x3": "tiles numbered 0-8 (3x3 grid, left-to-right, top-to-bottom)",
            "4x4": "tiles numbered 0-15 (4x4 grid)",
            "2x3": "tiles numbered 0-5 (2x3 grid)"
        }

        prompt = f"""You are a CAPTCHA classification assistant.

Analyze this CAPTCHA image and identify which tiles contain the requested object.

Instructions:
- The image is divided into {grid_info.get(grid_size, grid_info['3x3'])}
- Task: {instruction}
- Return ONLY a JSON array with tile indices to click
- Example: [0, 3, 6] means click tiles 0, 3, and 6
- If no tiles match, return: []
- Do NOT include explanations, only the JSON array

JSON response:"""

        return prompt

    async def _call_qwen_cli(self, image_path: Path, prompt: str) -> str:
        """
        Вызывает qw2 CLI для классификации изображения

        Использует qwen CLI с --json-schema для структурированного вывода.
        Картинка уходит в запрос как вложение (@путь + --include-directories),
        инструментов у модели нет: содержимое страницы считается враждебным.
        """
        try:
            # Создаем JSON schema для структурированного ответа
            schema_file = self.temp_dir / "schema.json"
            schema = {
                "type": "object",
                "properties": {
                    "indices": {
                        "type": "array",
                        "items": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 15
                        },
                        "description": "Array of tile indices to click"
                    }
                },
                "required": ["indices"]
            }

            with open(schema_file, "w") as f:
                json.dump(schema, f)

            # Команда-песочница (порядок аргументов проверен на CLI 0.27.1 —
            # по отдельности эти флаги оставляют модели лишние инструменты):
            # @путь + --include-directories кладут картинку в первый запрос
            # как вложение, --approval-mode plan и --max-tool-calls 0 запрещают
            # любое действие, --core-tools structured_output оставляет ровно
            # один инструмент (ответ по схеме), --exclude-tools снимает
            # остальные, включая tool_call, через который достижимы agent,
            # web_fetch и cron_*.
            absolute_image_path = str(image_path.resolve())

            cmd = [
                "qwen",
                "-m", self.vision_model,  # Use configured vision model
                f"Analyze the CAPTCHA image at @{absolute_image_path}. {prompt}",
                "--include-directories", str(self.temp_dir),
                "--json-schema", f"@{schema_file}",
                "--output-format", "json",
                "--approval-mode", "plan",
                "--max-tool-calls", "0",
                "--core-tools", "structured_output",
                "--exclude-tools", *EXCLUDED_TOOLS,
                "--max-wall-time", "60s"  # Max 60 seconds for vision analysis
            ]

            print(f"🔍 Calling qwen with model={self.vision_model}, image: {image_path}")

            # Run subprocess with timeout. The child inherits our environment:
            # the YOLO warning suppression is gone together with the modes that
            # auto-approved actions.
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            # Add Python-level timeout (Claude's finding #1). Both handlers
            # kill the child's process group and reap it with a bound: `kill()`
            # alone leaves a zombie (timeout) or a live qwen process holding the
            # image (cancellation, which the outer `except Exception` never sees).
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=90.0  # 90 seconds Python timeout (60s qwen + 30s buffer)
                )
            except asyncio.TimeoutError:
                print(f"❌ qwen process timed out after 90 seconds")
                await _reap(process)
                raise RuntimeError("Vision LLM classification timed out")
            except asyncio.CancelledError:
                await _reap(process)
                raise

            # Parse JSON output
            output = stdout.decode().strip()
            print(f"📥 Received output from qwen ({len(output)} bytes, exit code: {process.returncode})")

            # qwen may exit with code 1 even when successful (warnings, etc.)
            # We check if we have valid output with structured_result

            # Parse the entire output as JSON
            # The output can be either:
            # 1. A JSON array of events: [{"type":...}, {"type":...}]
            # 2. JSONL: one JSON object per line

            result_found = False
            last_assistant_text = None

            try:
                # Try to parse as a single JSON array
                if output.startswith('['):
                    events = json.loads(output)
                    print(f"   Parsed as JSON array with {len(events)} events")
                else:
                    # Try to parse as JSONL
                    events = []
                    for line in output.split('\n'):
                        if line.strip():
                            events.append(json.loads(line))
                    print(f"   Parsed as JSONL with {len(events)} events")

                # Process events
                for data in events:
                    if not isinstance(data, dict):
                        continue

                    # Check for structured result
                    if data.get('type') == 'result' and 'structured_result' in data:
                        result = data['structured_result']
                        print(f"✅ qwen response (structured): {_answer_summary(result)}")
                        result_found = True
                        return json.dumps(result)

                    # Also capture last assistant text message (in case structured_output failed)
                    if data.get('type') == 'assistant' and 'message' in data:
                        message = data['message']
                        if isinstance(message, dict) and 'content' in message:
                            content = message['content']
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        last_assistant_text = item.get('text', '')
                                        print(f"   Found assistant text ({len(last_assistant_text)} chars)")

            except json.JSONDecodeError as e:
                print(f"⚠️ Failed to parse output as JSON: {e}")
                return "{}"

            # If no structured result, try to parse last assistant text as JSON
            if not result_found and last_assistant_text:
                print(f"⚠️ No structured_result found, parsing assistant text ({len(last_assistant_text)} chars)")

                # Try multiple methods to extract JSON array
                text = last_assistant_text.strip()

                # Method 1: Extract from markdown code block
                import re
                markdown_json = re.search(r'```(?:json)?\s*\n?(\[.*?\])\s*\n?```', text, re.DOTALL)
                if markdown_json:
                    try:
                        indices = json.loads(markdown_json.group(1))
                        if isinstance(indices, list):
                            result = {"indices": indices}
                            print(f"✅ qwen response (from markdown): {_answer_summary(result)}")
                            return json.dumps(result)
                    except json.JSONDecodeError:
                        pass

                # Method 2: Find JSON array anywhere in text
                json_arrays = re.findall(r'\[[\d\s,]+\]', text)
                if json_arrays:
                    # Try the last JSON array (usually the final answer)
                    for json_str in reversed(json_arrays):
                        try:
                            indices = json.loads(json_str)
                            if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
                                result = {"indices": indices}
                                print(f"✅ qwen response (from text): {_answer_summary(result)}")
                                return json.dumps(result)
                        except json.JSONDecodeError:
                            continue

                # Method 3: Try to parse entire text as JSON
                try:
                    indices = json.loads(text)
                    if isinstance(indices, list):
                        result = {"indices": indices}
                        print(f"✅ qwen response (parsed): {_answer_summary(result)}")
                        return json.dumps(result)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"⚠️ Failed to parse text as JSON: {e}")

            print(f"⚠️ No structured_result found in output")
            print(f"   Last assistant text: {len(last_assistant_text or '')} chars")
            return "{}"

        except FileNotFoundError as e:
            print(f"❌ qwen command not found: {e}")
            raise RuntimeError("qwen CLI not installed - cannot classify CAPTCHA")
        except Exception as e:
            print(f"❌ qwen call failed: {e}")
            raise RuntimeError(f"Vision LLM classification failed: {e}")

    async def _fallback_classify(self, image_path: Path, prompt: str) -> str:
        """
        Fallback метод если qw2 CLI недоступен

        Выбрасывает исключение вместо возврата пустого списка
        (Codex's finding #2 - empty list is indistinguishable from success)
        """
        print(f"⚠️ qw2 CLI not available")
        print(f"   Image: {image_path}")
        print(f"   Prompt: {prompt[:100]}...")

        # Raise exception instead of returning empty list
        raise RuntimeError("qwen CLI not available - cannot classify CAPTCHA")

    def _parse_response(self, response: str) -> List[int]:
        """Парсит JSON ответ от vision model и удаляет дубликаты"""

        try:
            # Try to parse as JSON
            data = json.loads(response.strip())

            # If it's a dict with "indices" key (from structured output)
            if isinstance(data, dict) and "indices" in data:
                indices = data["indices"]
                if isinstance(indices, list):
                    # Remove duplicates (Codex's finding #3)
                    unique_indices = list(set([int(x) for x in indices if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]))
                    return sorted(unique_indices)

            # If it's a dict, try to extract the array
            if isinstance(data, dict):
                data = data.get("objects", data.get("tiles", data.get("answer", [])))

            # If it's already a list of integers
            if isinstance(data, list):
                # Remove duplicates
                unique_indices = list(set([int(x) for x in data if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]))
                return sorted(unique_indices)

            return []

        except json.JSONDecodeError:
            # Try to extract numbers from text
            import re
            numbers = re.findall(r'\b\d+\b', response)

            # Filter to valid tile indices
            max_tiles = 16  # Max for 4x4 grid
            return [int(n) for n in numbers if 0 <= int(n) < max_tiles]

    def cleanup(self):
        """Удаляет временные файлы"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# Alternative: Simple direct call approach
async def classify_with_qwen_simple(image_path: str, instruction: str) -> List[int]:
    """
    Простой способ классификации через внешний вызов

    Usage:
        indices = await classify_with_qwen_simple("captcha.png", "Select all bicycles")
        # Returns: [0, 3, 6]
    """
    # This would integrate with the actual qw2 tool
    # For now, using placeholder logic

    print(f"🤖 Classifying with qw2: {instruction}")
    print(f"   Image: {image_path}")

    # TODO: Actual qw2 integration
    # For testing, return placeholder
    return [0, 1, 2]


if __name__ == "__main__":
    # Test the classifier
    async def test():
        classifier = VisionLLMClassifier()

        # Test with a sample image
        test_image = b"fake_image_data"

        result = await classifier.classify_tiles(
            test_image,
            "Select all bicycles",
            "3x3"
        )

        print(f"Result: {result}")

        classifier.cleanup()

    asyncio.run(test())