#!/usr/bin/env python3
"""Simple test: solve real CAPTCHA with Vision LLM"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from workers.classifiers.vision_llm import VisionLLMClassifier


async def test_real_captcha():
    """Test Vision LLM with a real CAPTCHA screenshot"""

    print("=" * 60)
    print("Testing Vision LLM with real CAPTCHA")
    print("=" * 60)

    # Check for test images
    test_dir = Path("/home/deploy/github/anticaptcha/data/captchas")

    if not test_dir.exists():
        print(f"\n⚠️ No test images found. Create directory: {test_dir}")
        print(f"   Place CAPTCHA screenshots there and run again.")
        return

    # Find all PNG files
    test_images = list(test_dir.glob("*.png"))

    if not test_images:
        print(f"\n⚠️ No PNG files in {test_dir}")
        print(f"   Add some CAPTCHA screenshots and run again.")
        return

    print(f"\n📸 Found {len(test_images)} test images")

    # Initialize classifier
    classifier = VisionLLMClassifier()

    # Test each image
    for i, image_path in enumerate(test_images[:3], 1):  # Test first 3
        print(f"\n--- Test {i}/{min(len(test_images), 3)} ---")
        print(f"Image: {image_path.name}")

        # Read image
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        print(f"Size: {len(image_bytes)} bytes")

        # Ask user for instruction
        instruction = input(f"Enter instruction (e.g., 'Select all cars'): ").strip()

        if not instruction:
            instruction = "Select all tiles with the requested object"

        print(f"Instruction: {instruction}")

        # Classify
        try:
            indices = await classifier.classify_tiles(
                image_bytes,
                instruction,
                grid_size="3x3"
            )

            print(f"\n✅ Result: {indices}")
            print(f"   Tiles to click: {len(indices)}")

        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

    # Cleanup
    classifier.cleanup()

    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    asyncio.run(test_real_captcha())