#!/usr/bin/env python3
"""Test model detection on sample image"""
import sys
sys.path.insert(0, '/app')

from pathlib import Path
from PIL import Image
import io

try:
    from ultralytics import YOLO
    import numpy as np
    
    print("Testing model detection capabilities...")
    
    # Load custom model
    model_path = Path('/app/runs/detect/recaptcha_custom/weights/best.pt')
    if model_path.exists():
        print(f"✅ Loading custom model: {model_path}")
        model = YOLO(str(model_path))
        
        # Get class names
        print("\nClasses in custom model:")
        for idx, name in model.names.items():
            print(f"  {idx}: {name}")
    else:
        print(f"❌ Custom model not found at {model_path}")
        sys.exit(1)
    
    # Create a test image (random noise to see what model predicts)
    print("\nCreating test image...")
    test_img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    img = Image.fromarray(test_img)
    
    # Run inference with very low threshold
    print("\nRunning inference with very low threshold (0.01)...")
    results = model(np.array(img), conf=0.01, verbose=True)
    
    if results and len(results) > 0:
        print(f"\nResults: {len(results)} detections")
        for i, box in enumerate(results[0].boxes):
            class_id = int(box.cls[0])
            class_name = results[0].names[class_id]
            confidence = float(box.conf[0])
            print(f"  Detection {i+1}: {class_name} (conf: {confidence:.4f})")
    else:
        print("No detections")
    
    # Test with pretrained model for comparison
    pretrained_path = Path('/app/data/yolov8n.pt')
    if pretrained_path.exists():
        print(f"\n✅ Loading pretrained model for comparison: {pretrained_path}")
        pretrained = YOLO(str(pretrained_path))
        
        print("\nClasses in pretrained model:")
        for idx, name in list(pretrained.names.items())[:20]:  # Show first 20
            print(f"  {idx}: {name}")
        
        print("\nRunning pretrained inference with low threshold...")
        results2 = pretrained(np.array(img), conf=0.01, verbose=True)
        
        if results2 and len(results2) > 0:
            print(f"\nResults: {len(results2)} detections")
            for i, box in enumerate(results2[boxes]):
                if i >= 10:  # Limit output
                    break
                class_id = int(box.cls[0])
                class_name = results2[0].names[class_id]
                confidence = float(box.conf[0])
                print(f"  Detection {i+1}: {class_name} (conf: {confidence:.4f})")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()