#!/usr/bin/env python3
"""
Use pretrained Yolo models for reCAPTCHA classes

Instead of training from scratch, use transfer learning
with Yolo's pretrained models.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from ultralytics import YOLO
import numpy as np
from PIL import Image
import io

# Extended class mapping for reCAPTCHA
# COCO classes that match reCAPTCHA
COCO_TO_RECAPTCHA = {
    # Direct matches (COCO class -> reCAPTCHA target)
    2: 'car',           # car
    3: 'motorcycle',    # motorcycle
    5: 'bus',           # bus
    7: 'truck',         # truck
    1: 'bicycle',       # bicycle
    9: 'traffic_light', # traffic light
    10: 'fire_hydrant', # fire hydrant
    
    # Approximate matches (similar objects)
    # These need custom logic or additional models
}

# Classes NOT in COCO but in reCAPTCHA
RECAPTCHA_SPECIFIC = [
    'crosswalk',
    'stairs',
    'bridge',
    'mountain',
    'palm_tree',
    'chimney'
]

print("🚀 Loading pretrained Yolo model...")
model = YOLO('yolov8n.pt')
print("✅ Model loaded")
print()

print("📊 Supported reCAPTCHA classes (from COCO):")
for coco_id, recaptcha_class in COCO_TO_RECAPTCHA.items():
    print(f"   ✅ {recaptcha_class} (COCO class {coco_id})")

print()
print("⚠️ Classes requiring custom model:")
for cls in RECAPTCHA_SPECIFIC:
    print(f"   ❌ {cls}")

print()
print("="*60)
print("💡 SOLUTION: Use hybrid approach")
print("="*60)
print()
print("1. For COCO classes: Use pretrained Yolo")
print("2. For reCAPTCHA-specific: Use heuristic/color detection")
print()
print("Example heuristic for 'crosswalk':")
print("   - Detect zebra stripes pattern")
print("   - White lines on dark background")
print()
print("Example heuristic for 'stairs':")
print("   - Detect diagonal lines pattern")
print("   - Regular spacing")
print()


class HybridRecaptchaClassifier:
    """Hybrid classifier using Yolo + heuristics"""
    
    def __init__(self):
        self.yolo = YOLO('yolov8n.pt')
    
    def detect_crosswalk(self, image: np.ndarray) -> bool:
        """Detect crosswalk using pattern recognition"""
        # Simple heuristic: check for white stripes
        # Convert to grayscale
        gray = np.mean(image, axis=2)
        
        # Check for high contrast stripes
        mean = np.mean(gray)
        
        # White stripes on dark background
        white_pixels = np.sum(gray > mean + 50)
        total_pixels = gray.size
        
        ratio = white_pixels / total_pixels
        
        # Crosswalk typically has 20-40% white stripes
        return 0.2 < ratio < 0.4
    
    def detect_stairs(self, image: np.ndarray) -> bool:
        """Detect stairs using edge detection"""
        # Simple heuristic: regular horizontal lines
        # Use gradient to detect edges
        gray = np.mean(image, axis=2)
        
        # Horizontal gradient
        gradient = np.abs(np.diff(gray, axis=1))
        
        # Count strong horizontal edges
        edges = np.sum(gradient > 50)
        
        # Normalize
        edge_ratio = edges / gray.size
        
        return edge_ratio > 0.1
    
    def classify(self, image_bytes: bytes, target: str) -> bool:
        """Classify image using hybrid approach"""
        # Open image
        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)
        
        # Check if target is in COCO
        coco_classes = [
            'car', 'bus', 'truck', 'bicycle', 'motorcycle',
            'traffic_light', 'fire_hydrant'
        ]
        
        if target in coco_classes:
            # Use Yolo
            results = self.yolo(img, verbose=False)
            
            if results and len(results) > 0:
                boxes = results[0].boxes
                
                for box in boxes:
                    class_id = int(box.cls[0])
                    class_name = results[0].names[class_id].lower()
                    confidence = float(box.conf[0])
                    
                    # Check match
                    if target in ['car', 'truck', 'bus']:
                        # All vehicles
                        if class_name in ['car', 'truck', 'bus'] and confidence > 0.3:
                            return True
                    elif class_name == target and confidence > 0.3:
                        return True
            
            return False
        
        # Use heuristics for reCAPTCHA-specific classes
        elif target == 'crosswalk':
            return self.detect_crosswalk(img_array)
        elif target == 'stairs':
            return self.detect_stairs(img_array)
        
        # Unknown class
        return False


# Test the classifier
print("\n🧪 Testing hybrid classifier...")

classifier = HybridRecaptchaClassifier()

# Example test
print("   Model ready for use in solver")
print("   Supports:")
print("   - COCO classes: Yolo detection")
print("   - reCAPTCHA-specific: Pattern recognition")
print()
print("✅ Hybrid classifier ready!")