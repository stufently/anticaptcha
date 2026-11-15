#!/usr/bin/env python3
"""
Train custom Yolo model on reCAPTCHA images

This script trains a Yolo model on collected reCAPTCHA images.
Uses auto-annotation with pretrained COCO model for initial bounding boxes.
"""
import sys
import os
from pathlib import Path
import json
import shutil

sys.path.insert(0, '/app')

from ultralytics import YOLO
import numpy as np
from PIL import Image

# Dataset paths
DATASET_DIR = Path('/app/data/recaptcha_dataset')
IMAGES_DIR = DATASET_DIR / 'images'
YOLO_DIR = DATASET_DIR / 'yolo'

# Training parameters
EPOCHS = 100
IMG_SIZE = 640
BATCH_SIZE = 16
DEVICE = 'cpu'  # Use 'cuda' if GPU available


def auto_annotate_images():
    """
    Auto-annotate images using pretrained COCO model
    
    For reCAPTCHA images, the entire image is usually the object,
    so we create bounding boxes covering the full image.
    """
    print("\n🔄 Auto-annotating images with full-image bounding boxes...")
    
    # Load metadata
    metadata_file = DATASET_DIR / 'metadata.json'
    if not metadata_file.exists():
        print("❌ No metadata.json found. Run collect_recaptcha_dataset.py first.")
        return False
    
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    # Get unique classes
    classes = sorted(set(item['target'] for item in metadata))
    class_to_id = {cls: i for i, cls in enumerate(classes)}
    
    print(f"📊 Found {len(classes)} classes: {', '.join(classes)}")
    print(f"📊 Total images: {len(metadata)}")
    
    # Create YOLO structure
    train_images = YOLO_DIR / 'images' / 'train'
    train_labels = YOLO_DIR / 'labels' / 'train'
    train_images.mkdir(parents=True, exist_ok=True)
    train_labels.mkdir(parents=True, exist_ok=True)
    
    # Save classes file
    classes_file = YOLO_DIR / 'classes.txt'
    with open(classes_file, 'w') as f:
        f.write('\n'.join(classes))
    
    # Create dataset.yaml
    dataset_yaml = YOLO_DIR / 'dataset.yaml'
    with open(dataset_yaml, 'w') as f:
        f.write(f"""
path: {YOLO_DIR}
train: images/train
val: images/train

nc: {len(classes)}
names: {classes}
""")
    
    # Annotate each image
    print("\n📝 Annotating images...")
    for i, item in enumerate(metadata):
        image_path = IMAGES_DIR / item['filename']
        
        if not image_path.exists():
            print(f"   ⚠️ Image not found: {item['filename']}")
            continue
        
        # Get image dimensions
        img = Image.open(image_path)
        width, height = img.size
        
        # For reCAPTCHA tiles, the entire image is the object
        # YOLO format: class_id center_x center_y width height (normalized 0-1)
        class_id = class_to_id[item['target']]
        
        # Full image bounding box (center at 0.5, 0.5, size 1.0 x 1.0)
        label = f"{class_id} 0.5 0.5 1.0 1.0\n"
        
        # Copy image to YOLO directory
        dest_image = train_images / item['filename']
        if not dest_image.exists():
            shutil.copy(image_path, dest_image)
        
        # Save label
        label_file = train_labels / (item['filename'].rsplit('.', 1)[0] + '.txt')
        with open(label_file, 'w') as f:
            f.write(label)
        
        if (i + 1) % 10 == 0:
            print(f"   [{i+1}/{len(metadata)}] Annotated {i+1} images")
    
    print(f"\n✅ Auto-annotation complete!")
    print(f"   Images: {train_images}")
    print(f"   Labels: {train_labels}")
    
    return True


def train_model():
    """Train Yolo model on annotated dataset"""
    print("\n🚀 Training custom Yolo model...")
    print(f"   Epochs: {EPOCHS}")
    print(f"   Image size: {IMG_SIZE}")
    print(f"   Batch size: {BATCH_SIZE}")
    print(f"   Device: {DEVICE}")
    
    # Load pretrained model (transfer learning)
    # Try local file first, then default
    local_model = Path('/app/data/yolov8n.pt')
    if local_model.exists():
        print(f"   Using local model: {local_model}")
        model = YOLO(str(local_model))
    else:
        print("   Using default model (will download if needed)")
        model = YOLO('yolov8n.pt')
    
    # Train on custom dataset
    results = model.train(
        data=str(YOLO_DIR / 'dataset.yaml'),
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=BATCH_SIZE,
        device=DEVICE,
        pretrained=True,
        optimizer='auto',
        verbose=True,
        save=True,
        project='runs/detect',
        name='recaptcha_custom'
    )
    
    print(f"\n✅ Training complete!")
    print(f"   Model saved to: runs/detect/recaptcha_custom/weights/best.pt")
    
    return results


def validate_model():
    """Validate trained model on test images"""
    print("\n🧪 Validating trained model...")
    
    # Load best model
    best_model_path = Path('runs/detect/recaptcha_custom/weights/best.pt')
    if not best_model_path.exists():
        print("❌ Trained model not found. Run training first.")
        return
    
    model = YOLO(str(best_model_path))
    
    # Validate on test images
    results = model.val(data=str(YOLO_DIR / 'dataset.yaml'))
    
    print(f"\n📊 Validation results:")
    print(f"   mAP@0.5: {results.box.map50}")
    print(f"   mAP@0.5:0.95: {results.box.map}")
    
    return results


def main():
    """Main training workflow"""
    print("="*70)
    print("🎯 Custom Yolo Training for reCAPTCHA")
    print("="*70)
    
    # Check if images exist
    if not IMAGES_DIR.exists():
        print(f"\n❌ No images found at {IMAGES_DIR}")
        print("   Run collect_recaptcha_dataset.py first to collect images.")
        return
    
    # Step 1: Auto-annotate
    if not auto_annotate_images():
        return
    
    # Step 2: Train
    results = train_model()
    
    # Step 3: Validate
    validate_model()
    
    print("\n" + "="*70)
    print("🎉 Training Complete!")
    print("="*70)
    print("\n📋 Next steps:")
    print("   1. Update workers/solvers/recaptcha.py to use custom model:")
    print("      self.yolo_model = YOLO('runs/detect/recaptcha_custom/weights/best.pt')")
    print("   2. Test on real CAPTCHAs: python test_multiple_sites.py")
    print("   3. Compare success rate with pretrained model")


if __name__ == "__main__":
    main()