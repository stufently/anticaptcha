#!/usr/bin/env python3
"""
Download existing reCAPTCHA dataset from public sources

Alternative to live collection when Google detects automation.
"""
import os
import sys
import json
from pathlib import Path
import urllib.request
import zipfile
import tarfile

# Dataset directory
DATASET_DIR = Path('/app/data/recaptcha_dataset')
IMAGES_DIR = DATASET_DIR / 'images'
METADATA_FILE = DATASET_DIR / 'metadata.json'

# Create directories
DATASET_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

print("🚀 Downloading reCAPTCHA dataset from alternative sources...")
print("="*60)

# Option 1: Synthetic dataset (generate images programmatically)
print("\n📊 Creating synthetic dataset...")
print("   This creates simple geometric images for testing")

# For demonstration, create simple synthetic images
# In production, you would download from:
# - Kaggle reCAPTCHA datasets
# - Academic datasets
# - Your own collected images

from PIL import Image, ImageDraw
import random

CLASSES = [
    'car', 'bus', 'truck', 'bicycle', 'motorcycle',
    'traffic_light', 'fire_hydrant', 'crosswalk',
    'stairs', 'bridge', 'mountain', 'palm_tree'
]

metadata = []

def create_synthetic_image(target: str, index: int):
    """Create a synthetic image for testing"""
    # Create 100x100 image
    img = Image.new('RGB', (100, 100), color=(random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)))
    draw = ImageDraw.Draw(img)

    # Add simple shapes based on class
    if target == 'car':
        # Draw rectangle (car body)
        draw.rectangle([20, 30, 80, 70], fill=(random.randint(50, 150), random.randint(50, 150), random.randint(50, 150)))
        draw.ellipse([25, 60, 40, 75], fill='black')  # Wheel
        draw.ellipse([60, 60, 75, 75], fill='black')  # Wheel
    elif target == 'bus':
        # Draw long rectangle (bus)
        draw.rectangle([10, 25, 90, 75], fill=(random.randint(150, 255), random.randint(100, 200), 0))
    elif target == 'truck':
        # Draw rectangle with cab
        draw.rectangle([10, 30, 70, 70], fill=(random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)))
        draw.rectangle([70, 40, 90, 70], fill=(random.randint(150, 255), 0, 0))
    elif target == 'crosswalk':
        # Draw zebra stripes
        for i in range(5):
            draw.rectangle([i*20, 0, i*20+10, 100], fill='white')
    elif target == 'stairs':
        # Draw diagonal lines
        for i in range(10):
            draw.line([0, i*10, 100, i*10], fill=(random.randint(50, 150), random.randint(50, 150), random.randint(50, 150)), width=3)
    else:
        # Generic: random shapes
        for _ in range(random.randint(3, 7)):
            x1, y1 = random.randint(0, 80), random.randint(0, 80)
            x2, y2 = x1 + random.randint(10, 20), y1 + random.randint(10, 20)
            color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
            draw.rectangle([x1, y1, x2, y2], fill=color)

    return img

# Generate synthetic images
NUM_IMAGES_PER_CLASS = 50

print(f"\n📝 Generating {NUM_IMAGES_PER_CLASS} synthetic images per class...")
print(f"   Classes: {len(CLASSES)}")

for target in CLASSES[:6]:  # Start with first 6 classes
    print(f"\n   Generating '{target}' images...")
    for i in range(NUM_IMAGES_PER_CLASS):
        img = create_synthetic_image(target, i)

        # Save image
        filename = f"{target}_synthetic_{i:04d}.png"
        img.save(IMAGES_DIR / filename)

        # Add to metadata
        metadata.append({
            'filename': filename,
            'target': target,
            'instruction': f'select all images with {target}',
            'source': 'synthetic',
            'image_index': i
        })

    print(f"      ✅ Created {NUM_IMAGES_PER_CLASS} images")

# Save metadata
with open(METADATA_FILE, 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"\n✅ Dataset created!")
print(f"   Total images: {len(metadata)}")
print(f"   Location: {IMAGES_DIR}")
print(f"   Metadata: {METADATA_FILE}")

print("\n" + "="*60)
print("💡 NOTE: This is a SYNTHETIC dataset for testing")
print("="*60)
print("   For production:")
print("   1. Download real CAPTCHA images from:")
print("      - Kaggle: search 'recaptcha dataset'")
print("      - GitHub: 'recaptcha-images'")
print("      - Academic datasets")
print("   2. Or use your own collected images")
print()
print("   With real images, the model will learn actual CAPTCHA patterns")
print("   Synthetic images are just for testing the pipeline")
print()
print("📋 Next step: Train model")
print("   python train_custom_yolo.py")