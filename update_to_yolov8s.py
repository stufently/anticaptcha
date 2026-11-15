#!/usr/bin/env python3
"""Add YOLOv8s support and conservative selection strategy"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Update setup to try larger model
old_setup = '''"""Setup solver and load Yolo model"""
        if HAS_ML:
            try:
                # Load BOTH models: custom for trained classes, pretrained for COCO classes
                custom_model_path = Path('/app/runs/detect/recaptcha_custom/weights/best.pt')
                pretrained_model_path = Path('/app/data/yolov8n.pt')
                
                # Custom model classes
                custom_classes = ['bicycle', 'bus', 'car', 'motorcycle', 'traffic_light', 'truck']
                
                # Load pretrained first (has all COCO classes)
                if pretrained_model_path.exists():
                    print(f"✅ Loading pretrained model for COCO classes")
                    self.yolo_model = YOLO(str(pretrained_model_path))
                else:
                    print("✅ Loading pretrained model (will download if needed)")
                    self.yolo_model = YOLO('yolov8n.pt')'''

new_setup = '''"""Setup solver and load Yolo model"""
        if HAS_ML:
            try:
                # Try larger, more accurate model first (YOLOv8s), then YOLOv8n
                custom_model_path = Path('/app/runs/detect/recaptcha_custom/weights/best.pt')
                large_pretrained_path = Path('/app/data/yolov8s.pt')
                small_pretrained_path = Path('/app/data/yolov8n.pt')
                
                # Custom model classes
                custom_classes = ['bicycle', 'bus', 'car', 'motorcycle', 'traffic_light', 'truck']
                
                # Load most accurate model available
                if large_pretrained_path.exists():
                    print(f"✅ Loading YOLOv8s (larger, more accurate)")
                    self.yolo_model = YOLO(str(large_pretrained_path))
                elif small_pretrained_path.exists():
                    print(f"✅ Loading YOLOv8n (smaller, faster)")
                    self.yolo_model = YOLO(str(small_pretrained_path))
                else:
                    print("✅ Loading pretrained model (will download if needed)")
                    self.yolo_model = YOLO('yolov8n.pt')'''

if old_setup in content:
    content = content.replace(old_setup, new_setup)
    
    # Now update selection strategy - be more conservative
    # Find the section where we select images
    old_select = '''            if should_select:
                print(f"   Image {i+1}: ✅ SELECT")
                await tile.click()
                selected.append(i)'''
    
    new_select = '''            if should_select:
                # Collect all detections for this image, select top ones later
                max_confidence = max([float(box.conf[0]) for box in boxes if float(box.conf[0]) >= MIN_CONFIDENCE] or [0])
                print(f"   Image {i+1}: ✅ CANDIDATE (max conf: {max_confidence:.2f})")
                candidates.append((i, max_confidence))'''
    
    if old_select in content:
        content = content.replace(old_select, new_select)
        print("✅ Updated to conservative selection strategy")
    
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Updated model loading to prefer YOLOv8s")
else:
    print("❌ Could not find setup section")