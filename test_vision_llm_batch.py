#!/usr/bin/env python3
"""Test Vision LLM on multiple synthetic CAPTCHA images"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from workers.classifiers.vision_llm import VisionLLMClassifier


async def test_batch():
    """Test Vision LLM on multiple images"""

    print("=" * 60)
    print("Testing Vision LLM on synthetic CAPTCHA images")
    print("=" * 60)

    # Test images directory
    test_dir = Path("/home/deploy/github/anticaptcha/data/recaptcha_dataset/images")

    # Test cases: (filename_pattern, instruction, expected_object)
    test_cases = [
        ("car_synthetic_0000.png", "Select all tiles with cars", "car"),
        ("bicycle_synthetic_0000.png", "Select all tiles with bicycles", "bicycle"),
        ("bus_synthetic_0000.png", "Select all tiles with buses", "bus"),
        ("truck_synthetic_0000.png", "Select all tiles with trucks", "truck"),
    ]

    # Initialize classifier
    classifier = VisionLLMClassifier()

    # Track results
    results = []

    # Test each case
    for i, (filename, instruction, obj) in enumerate(test_cases, 1):
        image_path = test_dir / filename

        if not image_path.exists():
            print(f"\n⚠️ [{i}/{len(test_cases)}] Image not found: {filename}")
            continue

        print(f"\n--- Test {i}/{len(test_cases)} ---")
        print(f"File: {filename}")
        print(f"Object: {obj}")
        print(f"Instruction: {instruction}")

        # Read image
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        print(f"Size: {len(image_bytes)} bytes")

        # Classify
        try:
            indices = await classifier.classify_tiles(
                image_bytes,
                instruction,
                grid_size="3x3"
            )

            print(f"✅ Result: {indices}")
            print(f"   Tiles to click: {len(indices)}")

            # For synthetic images, we expect at least some tiles to be selected
            # since the image contains the requested object
            success = len(indices) > 0

            results.append({
                "file": filename,
                "object": obj,
                "indices": indices,
                "success": success
            })

        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({
                "file": filename,
                "object": obj,
                "indices": [],
                "success": False,
                "error": str(e)
            })

    # Cleanup
    classifier.cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    successful = sum(1 for r in results if r.get("success", False))
    total = len(results)

    print(f"\nTests: {successful}/{total} successful")
    print(f"Success rate: {successful/total*100:.1f}%")

    print("\nDetails:")
    for r in results:
        status = "✅" if r.get("success") else "❌"
        print(f"{status} {r['file']:30s} {r['object']:10s} → {r['indices']}")

    print("\n" + "=" * 60)

    if successful == total:
        print("🎉 All tests passed!")
    else:
        print(f"⚠️ {total - successful} test(s) failed")


if __name__ == "__main__":
    asyncio.run(test_batch())