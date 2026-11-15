#!/usr/bin/env python3
"""Compare different models for CAPTCHA classification"""

import asyncio
import subprocess
import json
import time
from pathlib import Path
from typing import List, Dict, Any


class ModelComparison:
    """Test different models on CAPTCHA classification"""

    def __init__(self):
        self.results = []

    async def test_model(self, model: str, image_path: Path, instruction: str) -> Dict[str, Any]:
        """Test a single model on one image"""

        print(f"\n🤖 Testing model: {model}")

        # Create schema
        schema = {
            "type": "object",
            "properties": {
                "indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 15}
                }
            },
            "required": ["indices"]
        }

        schema_file = Path(f"/tmp/schema_{model}.json")
        with open(schema_file, "w") as f:
            json.dump(schema, f)

        # Build command
        cmd = [
            "qwen",
            f"Analyze the CAPTCHA image at {image_path}. {instruction}",
            "--model", model,
            "--json-schema", f"@{schema_file}",
            "--output-format", "json",
            "--yolo",
            "--max-wall-time", "60s"
        ]

        # Set env
        env = {
            **subprocess.os.environ,
            "QWEN_CODE_SUPPRESS_YOLO_WARNING": "1"
        }

        # Run and measure time
        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await process.communicate()
            elapsed_time = time.time() - start_time

            # Parse output
            output = stdout.decode().strip()
            indices = self._extract_indices(output)

            return {
                "model": model,
                "success": True,
                "indices": indices,
                "time": elapsed_time,
                "exit_code": process.returncode
            }

        except Exception as e:
            elapsed_time = time.time() - start_time
            return {
                "model": model,
                "success": False,
                "error": str(e),
                "time": elapsed_time,
                "indices": []
            }

    def _extract_indices(self, output: str) -> List[int]:
        """Extract indices from model output"""

        import re

        # Try to parse as JSON array
        try:
            if output.startswith('['):
                events = json.loads(output)
            else:
                events = []
                for line in output.split('\n'):
                    if line.strip():
                        events.append(json.loads(line))

            # Find structured_result
            for data in events:
                if isinstance(data, dict):
                    if data.get('type') == 'result' and 'structured_result' in data:
                        result = data['structured_result']
                        if isinstance(result, dict) and 'indices' in result:
                            return result['indices']

                    # Find text
                    if data.get('type') == 'assistant' and 'message' in data:
                        message = data['message']
                        if isinstance(message, dict) and 'content' in message:
                            content = message['content']
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        text = item.get('text', '')
                                        # Extract JSON array
                                        json_arrays = re.findall(r'\[[\d\s,]+\]', text)
                                        if json_arrays:
                                            for json_str in reversed(json_arrays):
                                                try:
                                                    indices = json.loads(json_str)
                                                    if isinstance(indices, list) and all(isinstance(i, int) for i in indices):
                                                        return indices
                                                except:
                                                    continue
        except:
            pass

        return []

    async def compare_models(self, models: List[str], test_images: List[tuple]):
        """Compare multiple models on test images"""

        print("=" * 60)
        print("MODEL COMPARISON FOR CAPTCHA CLASSIFICATION")
        print("=" * 60)

        print(f"\nModels to test: {len(models)}")
        for model in models:
            print(f"  - {model}")

        print(f"\nTest images: {len(test_images)}")

        # Test each model on each image
        for model in models:
            print(f"\n{'=' * 60}")
            print(f"Testing model: {model}")
            print(f"{'=' * 60}")

            model_results = []

            for image_path, instruction, expected_obj in test_images:
                if not image_path.exists():
                    print(f"⚠️ Image not found: {image_path.name}")
                    continue

                print(f"\n📷 {image_path.name} ({expected_obj})")

                result = await self.test_model(model, image_path, instruction)
                result['image'] = image_path.name
                result['expected'] = expected_obj

                model_results.append(result)

                # Print result
                if result['success']:
                    print(f"   ✅ Indices: {result['indices']}")
                    print(f"   ⏱️  Time: {result['time']:.1f}s")
                else:
                    print(f"   ❌ Error: {result.get('error', 'Unknown')}")

            # Calculate stats for this model
            successful = sum(1 for r in model_results if r['success'] and r['indices'])
            total = len(model_results)
            avg_time = sum(r['time'] for r in model_results) / total if total > 0 else 0

            print(f"\n📊 Model {model} stats:")
            print(f"   Success: {successful}/{total}")
            print(f"   Avg time: {avg_time:.1f}s")

            self.results.append({
                "model": model,
                "results": model_results,
                "stats": {
                    "successful": successful,
                    "total": total,
                    "avg_time": avg_time
                }
            })

        # Summary
        print("\n" + "=" * 60)
        print("FINAL COMPARISON")
        print("=" * 60)

        print(f"\n{'Model':<20} {'Success':<15} {'Avg Time':<15}")
        print("-" * 50)

        for r in sorted(self.results, key=lambda x: x['stats']['successful'], reverse=True):
            model = r['model']
            stats = r['stats']
            success = f"{stats['successful']}/{stats['total']}"
            time = f"{stats['avg_time']:.1f}s"
            print(f"{model:<20} {success:<15} {time:<15}")


async def main():
    # Models to test
    models = [
        "kimi-k2.5",  # Current model
        "qwen-plus",  # Alibaba Qwen Plus
        "qwen-max",  # Alibaba Qwen Max
        "qwen-turbo",  # Alibaba Qwen Turbo
    ]

    # Test images (path, instruction, expected object)
    test_dir = Path("/home/deploy/github/anticaptcha/data/recaptcha_dataset/images")
    test_images = [
        (test_dir / "car_synthetic_0000.png", "Select all tiles with cars", "car"),
        (test_dir / "bicycle_synthetic_0000.png", "Select all tiles with bicycles", "bicycle"),
        (test_dir / "bus_synthetic_0000.png", "Select all tiles with buses", "bus"),
        (test_dir / "truck_synthetic_0000.png", "Select all tiles with trucks", "truck"),
    ]

    # Run comparison
    comparison = ModelComparison()
    await comparison.compare_models(models, test_images)


if __name__ == "__main__":
    asyncio.run(main())