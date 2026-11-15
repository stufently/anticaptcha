#!/usr/bin/env python3
"""Test Vision LLM integration with qwen CLI"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from workers.classifiers.vision_llm import VisionLLMClassifier


async def test_vision_llm():
    """Test the vision LLM classifier"""

    print("=" * 60)
    print("Testing Vision LLM Classifier")
    print("=" * 60)

    # Initialize classifier
    classifier = VisionLLMClassifier()

    # Test with a sample image from dataset
    test_image_path = Path("/home/deploy/github/anticaptcha/data/recaptcha_dataset/images/car_synthetic_0000.png")

    if not test_image_path.exists():
        print(f"❌ Test image not found: {test_image_path}")
        return

    # Read image
    with open(test_image_path, "rb") as f:
        image_bytes = f.read()

    print(f"\n📸 Testing with image: {test_image_path.name}")
    print(f"   Image size: {len(image_bytes)} bytes")

    # Test classification
    instruction = "Select all tiles with cars"

    print(f"\n🎯 Instruction: {instruction}")
    print(f"   Grid size: 3x3")

    try:
        indices = await classifier.classify_tiles(
            image_bytes,
            instruction,
            grid_size="3x3"
        )

        print(f"\n✅ SUCCESS!")
        print(f"   Tiles to click: {indices}")
        print(f"   Number of tiles: {len(indices)}")

        # Success if we got valid indices
        if indices:
            print(f"\n🎉 Vision LLM is working!")
            print(f"   Expected to find tiles with cars")
            print(f"   Found {len(indices)} tiles: {indices}")
        else:
            print(f"\n⚠️ No tiles found")
            print(f"   The vision model might need tuning")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        classifier.cleanup()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_vision_llm())