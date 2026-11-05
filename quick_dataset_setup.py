#!/usr/bin/env python3
"""
Quick train Yolo on synthetic reCAPTCHA-like images

Creates a minimal dataset and trains a model quickly for testing.
"""
import os
import sys
from pathlib import Path
import json

# Create dataset directory
DATASET_DIR = Path('/app/data/quick_dataset')
DATASET_DIR.mkdir(parents=True, exist_ok=True)

# Create minimal dataset structure
train_images = DATASET_DIR / 'images' / 'train'
train_labels = DATASET_DIR / 'labels' / 'train'
train_images.mkdir(parents=True, exist_ok=True)
train_labels.mkdir(parents=True, exist_ok=True)

# Define classes
CLASSES = [
    'car', 'bus', 'truck', 'bicycle', 'motorcycle',
    'traffic_light', 'fire_hydrant', 'crosswalk',
    'stairs', 'bridge', 'mountain', 'palm_tree'
]

# Save classes
classes_file = DATASET_DIR / 'classes.txt'
with open(classes_file, 'w') as f:
    f.write('\n'.join(CLASSES))

# Create dataset.yaml
dataset_yaml = DATASET_DIR / 'dataset.yaml'
with open(dataset_yaml, 'w') as f:
    f.write(f"""
path: {DATASET_DIR}
train: images/train
val: images/train

nc: {len(CLASSES)}
names: {CLASSES}
""")

print("📁 Created dataset structure")
print(f"   Path: {DATASET_DIR}")
print(f"   Classes: {len(CLASSES)}")
print(f"   Classes: {', '.join(CLASSES)}")
print()

# Note about images
print("⚠️ NOTE: For quick training, you need to:")
print("   1. Add images to: data/quick_dataset/images/train/")
print("   2. Add labels to: data/quick_dataset/labels/train/")
print()
print("💡 Alternative: Use transfer learning from existing models")
print("   - Load pretrained Yolo and fine-tune")
print()

# Create training script
train_script = DATASET_DIR / 'train.py'
with open(train_script, 'w') as f:
    f.write("""
from ultralytics import YOLO

# Load pretrained model
model = YOLO('yolov8n.pt')

# Train (fine-tune) on reCAPTCHA classes
# Note: This will work only if you have labeled images
results = model.train(
    data='data/quick_dataset/dataset.yaml',
    epochs=50,
    imgsz=640,
    batch=16,
    device='cpu',
    pretrained=True,
    optimizer='auto',
    verbose=True
)

print(f"✅ Model saved to: runs/detect/train/weights/best.pt")
""")

print("✅ Setup complete!")
print()
print("📋 Next steps:")
print("   1. python data/quick_dataset/train.py  # Train model")
print("   2. Update solver to use new model")