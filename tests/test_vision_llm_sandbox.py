"""The vision LLM call must be a sandbox: no tools, no leftover images."""
import asyncio
import json
import pathlib

import pytest

from workers.classifiers.vision_llm import EXCLUDED_TOOLS, VisionLLMClassifier

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SETTINGS_PATH = REPO_ROOT / "config" / "qwen" / "settings.json"

# Everything that would let the model act instead of answering
FORBIDDEN_ARGV_TOKENS = {"auto", "auto-edit", "yolo", "--yolo", "-y"}

EXPECTED_EXCLUDED_TOOLS = {
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
}

STRUCTURED_ANSWER = json.dumps(
    [{"type": "result", "structured_result": {"indices": [0, 3]}}]
)


class FakeProcess:
    """Stands in for the qwen subprocess."""

    def __init__(self, stdout=STRUCTURED_ANSWER, returncode=0, exc=None):
        self.stdout = stdout
        self.returncode = returncode
        self.exc = exc
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self.exc is not None:
            raise self.exc
        return self.stdout.encode(), b""

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


def install_fake_exec(monkeypatch, process):
    calls = []

    async def fake_exec(*cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def make_classifier(monkeypatch):
    monkeypatch.setenv("BAILIAN_CODING_PLAN_API_KEY", "test-key")
    classifier = VisionLLMClassifier()
    assert classifier.enabled, "the classifier needs an API key to be testable"
    return classifier


def value_after(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def test_qwen_command_is_tool_free(monkeypatch):
    classifier = make_classifier(monkeypatch)
    calls = install_fake_exec(monkeypatch, FakeProcess())
    try:
        indices = asyncio.run(
            classifier.classify_tiles(b"fake-png-bytes", "Select all bicycles", "3x3")
        )
        temp_dir = classifier.temp_dir
    finally:
        classifier.cleanup()

    assert len(calls) == 1, f"the CLI must be called exactly once, got {len(calls)}"
    argv, kwargs = calls[0]
    assert argv[0] == "qwen", "the vision model must be called through the qwen CLI"

    assert value_after(argv, "--approval-mode") == "plan", (
        "the model must run in plan mode, never in an auto-approving one"
    )
    assert value_after(argv, "--max-tool-calls") == "0", (
        "the model must be allowed zero tool calls"
    )
    assert value_after(argv, "--core-tools") == "structured_output", (
        "only the schema answer tool may stay in the request"
    )
    assert value_after(argv, "--max-wall-time") == "60s", "the CLI wall clock must stay bounded"

    start = argv.index("--exclude-tools") + 1 if "--exclude-tools" in argv else None
    assert start is not None, "--exclude-tools must be present"
    end = start
    while end < len(argv) and not argv[end].startswith("-"):
        end += 1
    excluded = argv[start:end]
    assert set(excluded) == EXPECTED_EXCLUDED_TOOLS, (
        "--exclude-tools must cover every tool that escapes the sandbox"
    )
    assert excluded == EXCLUDED_TOOLS, "the module constant must be what is passed"

    assert value_after(argv, "--include-directories") == str(temp_dir), (
        "--include-directories must point at the directory holding the image"
    )

    prompt = argv[argv.index("-m") + 2]
    reference = next((tok for tok in prompt.split() if tok.startswith("@")), None)
    assert reference is not None, "the prompt must reference the image with @path"
    referenced = reference[1:].rstrip(".")
    assert pathlib.Path(referenced).is_absolute(), "the @path reference must be absolute"
    assert pathlib.Path(referenced).parent.resolve() == temp_dir.resolve(), (
        "the @path reference must be the temp captcha image"
    )
    assert prompt.split(reference, 1)[1][:1] in ("", " ", ".", "\n"), (
        "the @path reference must end at a space, dot, newline or end of prompt"
    )

    forbidden = FORBIDDEN_ARGV_TOKENS.intersection(argv)
    assert not forbidden, f"no auto-approving mode may appear in argv: {sorted(forbidden)}"

    env = kwargs.get("env")
    assert env is None or "QWEN_CODE_SUPPRESS_YOLO_WARNING" not in env, (
        "the YOLO warning suppression must be gone with the auto modes"
    )

    assert indices == [0, 3], f"the structured answer must be parsed, got {indices}"


def test_temp_image_removed_after_success(monkeypatch):
    classifier = make_classifier(monkeypatch)
    install_fake_exec(monkeypatch, FakeProcess())
    try:
        indices = asyncio.run(
            classifier.classify_tiles(b"fake-png-bytes", "Select all bicycles", "3x3")
        )
        leftovers = sorted(p.name for p in classifier.temp_dir.glob("captcha_*.png"))
    finally:
        classifier.cleanup()

    assert indices == [0, 3], f"the classification itself must work, got {indices}"
    assert leftovers == [], f"the temp captcha image must be removed, left: {leftovers}"


def test_temp_image_removed_after_failure(monkeypatch):
    classifier = make_classifier(monkeypatch)
    try:
        install_fake_exec(monkeypatch, FakeProcess(exc=RuntimeError("qwen crashed")))
        with pytest.raises(RuntimeError):
            asyncio.run(
                classifier.classify_tiles(b"fake-png-bytes", "Select all bicycles", "3x3")
            )
        after_crash = sorted(p.name for p in classifier.temp_dir.glob("captcha_*.png"))

        timed_out = FakeProcess(exc=asyncio.TimeoutError())
        install_fake_exec(monkeypatch, timed_out)
        with pytest.raises(RuntimeError):
            asyncio.run(
                classifier.classify_tiles(b"fake-png-bytes", "Select all bicycles", "3x3")
            )
        after_timeout = sorted(p.name for p in classifier.temp_dir.glob("captcha_*.png"))
    finally:
        classifier.cleanup()

    assert after_crash == [], f"a crashed CLI must not leave the image behind: {after_crash}"
    assert after_timeout == [], f"a timed out CLI must not leave the image behind: {after_timeout}"
    assert timed_out.killed, "a timed out CLI process must be killed"


def test_qwen_settings_disable_memory_agent():
    """The CLI would otherwise send a second request: a memory subagent with
    write_file/edit tools, driven by the same attacker-controlled content."""
    assert SETTINGS_PATH.is_file(), (
        f"config/qwen/settings.json must exist at {SETTINGS_PATH}"
    )
    loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    memory = loaded.get("memory")
    assert memory is not None, "qwen settings must carry a memory section"
    assert memory.get("enableManagedAutoMemory") is False, (
        "the auto-memory subagent must stay disabled"
    )
    assert memory.get("enableManagedAutoDream") is False, (
        "the auto-dream subagent must stay disabled"
    )
    assert loaded["security"]["auth"]["selectedType"] == "openai", (
        "the openai auth selection must stay"
    )
