#!/usr/bin/env python3
"""Add debug output to see model detections"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Add debug after running model
old_code = '''            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)

                if results and len(results) > 0:
                    boxes = results[0].boxes

                    # Use class-specific confidence thresholds'''

new_code = '''            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)

                if results and len(results) > 0:
                    boxes = results[0].boxes
                    
                    # Debug: Show all detections
                    if len(boxes) > 0:
                        print(f"      📦 Model detected {len(boxes)} objects")
                    else:
                        print(f"      📦 No objects detected by model")

                    # Use class-specific confidence thresholds'''

if old_code in content:
    content = content.replace(old_code, new_code)
    
    # Also add debug for each detection
    old_check = '''                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])

                        # Only return True for reasonable detections
                        if confidence < MIN_CONFIDENCE:
                            continue'''
    
    new_check = '''                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])
                        
                        # Debug: Show each detection
                        print(f"      - {class_name}: {confidence:.2f}")

                        # Only return True for reasonable detections
                        if confidence < MIN_CONFIDENCE:
                            print(f"        (below threshold {MIN_CONFIDENCE:.2f}, skipping)")
                            continue'''
    
    if old_check in content:
        content = content.replace(old_check, new_check)
    
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Added debug output to model detection")
else:
    print("❌ Could not find the code section")