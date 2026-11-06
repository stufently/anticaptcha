#!/usr/bin/env python3
"""Real-world comparison of Vision LLM models on CAPTCHA"""

import asyncio
import sys
import time
import json
import tempfile
from pathlib import Path

sys.path.insert(0, '/app')


class ModelComparison:
    """Compare different Vision LLM models on real CAPTCHA"""

    def __init__(self):
        self.results = {}
        self.test_images = []

    async def test_qwen(self, image_path: str, prompt: str) -> dict:
        """Test Qwen model"""
        start = time.time()

        try:
            import subprocess

            cmd = [
                "qwen",
                prompt,
                "--approval-mode", "auto",
                "--max-wall-time", "30s"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45
            )

            elapsed = time.time() - start

            return {
                "model": "Qwen2.5",
                "output": result.stdout.strip(),
                "time": elapsed,
                "success": result.returncode == 0,
                "error": None if result.returncode == 0 else result.stderr
            }

        except Exception as e:
            return {
                "model": "Qwen2.5",
                "output": None,
                "time": time.time() - start,
                "success": False,
                "error": str(e)
            }

    async def test_kimi(self, image_path: str, prompt: str) -> dict:
        """Test Kimi model (default in project)"""
        start = time.time()

        try:
            import subprocess

            # Kimi uses same qw2 CLI but different model endpoint
            cmd = [
                "qwen",
                prompt,
                "--approval-mode", "auto",
                "--max-wall-time", "30s",
                "--model", "kimi-k2.5"  # Explicitly specify Kimi
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45
            )

            elapsed = time.time() - start

            return {
                "model": "Kimi-k2.5",
                "output": result.stdout.strip(),
                "time": elapsed,
                "success": result.returncode == 0,
                "error": None if result.returncode == 0 else result.stderr
            }

        except Exception as e:
            return {
                "model": "Kimi-k2.5",
                "output": None,
                "time": time.time() - start,
                "success": False,
                "error": str(e)
            }

    async def test_deepseek(self, image_path: str, prompt: str) -> dict:
        """Test DeepSeek model"""
        start = time.time()

        try:
            import subprocess

            cmd = [
                "qwen",
                prompt,
                "--approval-mode", "auto",
                "--max-wall-time", "30s",
                "--model", "deepseek-v3"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45
            )

            elapsed = time.time() - start

            return {
                "model": "DeepSeek-V3",
                "output": result.stdout.strip(),
                "time": elapsed,
                "success": result.returncode == 0,
                "error": None if result.returncode == 0 else result.stderr
            }

        except Exception as e:
            return {
                "model": "DeepSeek-V3",
                "output": None,
                "time": time.time() - start,
                "success": False,
                "error": str(e)
            }

    async def compare_on_image(self, image_path: str, prompt: str, expected: str = None):
        """Compare all models on one image"""
        print(f"\n{'=' * 70}")
        print(f"Testing: {Path(image_path).name}")
        print(f"Prompt: {prompt}")
        if expected:
            print(f"Expected: {expected}")
        print(f"{'=' * 70}")

        results = {}

        # Test each model
        models = [
            ("Qwen2.5", self.test_qwen),
            ("Kimi-k2.5", self.test_kimi),
            ("DeepSeek-V3", self.test_deepseek),
        ]

        for model_name, test_func in models:
            print(f"\n🔄 Testing {model_name}...")
            result = await test_func(image_path, prompt)
            results[model_name] = result

            status = "✅" if result["success"] else "❌"
            print(f"{status} {model_name}: {result['output']}")
            print(f"   Time: {result['time']:.2f}s")

            if expected and result["output"]:
                # Check accuracy
                try:
                    # Try to parse as JSON
                    import re
                    json_match = re.search(r'\[.*?\]', result["output"])
                    if json_match:
                        predicted = json.loads(json_match.group(0))
                        expected_list = json.loads(expected)

                        correct = set(predicted) == set(expected_list)
                        result["accuracy"] = correct
                        print(f"   Accuracy: {'✅ Correct' if correct else '❌ Wrong'}")
                except:
                    pass

        return results

    def generate_report(self, all_results: list):
        """Generate comparison report"""
        print("\n" + "=" * 70)
        print("COMPARISON REPORT")
        print("=" * 70)

        for model_name in ["Qwen2.5", "Kimi-k2.5", "DeepSeek-V3"]:
            model_results = [r[model_name] for r in all_results if model_name in r]

            if not model_results:
                continue

            success_count = sum(1 for r in model_results if r["success"])
            total_time = sum(r["time"] for r in model_results)
            avg_time = total_time / len(model_results)

            accuracy_scores = [r.get("accuracy", None) for r in model_results]
            accuracy_scores = [a for a in accuracy_scores if a is not None]

            print(f"\n{model_name}:")
            print(f"  Success rate: {success_count}/{len(model_results)} ({success_count/len(model_results)*100:.0f}%)")
            print(f"  Average time: {avg_time:.2f}s")
            if accuracy_scores:
                accuracy = sum(accuracy_scores) / len(accuracy_scores) * 100
                print(f"  Accuracy: {accuracy:.0f}%")


async def main():
    """Run comparison"""
    print("🚀 REAL-WORLD MODEL COMPARISON")
    print("Testing Qwen, Kimi, DeepSeek on CAPTCHA images")
    print("=" * 70)

    comparison = ModelComparison()
    all_results = []

    # Test with synthetic CAPTCHA images if available
    test_cases = [
        {
            "image": "/app/data/synthetic/car_synthetic_0000.png",
            "prompt": "Analyze this reCAPTCHA image. Select all tiles with cars. Return JSON array of tile indices [0-8]. Image: /app/data/synthetic/car_synthetic_0000.png",
            "expected": "[4, 7]"
        },
    ]

    # Try to find test images
    synthetic_dir = Path("/app/data/synthetic")
    if synthetic_dir.exists():
        print("✅ Found synthetic images directory")

        # Find first car image
        car_images = list(synthetic_dir.glob("car_*.png"))
        if car_images:
            test_cases[0]["image"] = str(car_images[0])

    # Run tests
    for test_case in test_cases:
        if Path(test_case["image"]).exists():
            result = await comparison.compare_on_image(
                test_case["image"],
                test_case["prompt"],
                test_case.get("expected")
            )
            all_results.append(result)
        else:
            print(f"⚠️ Image not found: {test_case['image']}")

    # Generate report
    comparison.generate_report(all_results)

    print("\n" + "=" * 70)
    print("✅ Comparison complete!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())