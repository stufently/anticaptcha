#!/usr/bin/env python3
"""Adjust confidence thresholds for better detection"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find and replace the confidence section
old_section = '''            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)

                if results and len(results) > 0:
                    boxes = results[0].boxes

                    # Use higher confidence for more accurate detections
                    MIN_CONFIDENCE = 0.5  # Higher threshold for accuracy

                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])

                        # Only return True for reasonable detections
                        if confidence < MIN_CONFIDENCE:
                            continue

                        # Relaxed mapping for vehicles
                        if target == 'car':
                            # Accept car, also trucks/buses with high confidence
                            if class_name in ['car', 'truck', 'bus'] and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'bus':
                            # Accept bus and truck
                            if class_name in ['bus', 'truck'] and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'truck':
                            # Accept truck and bus
                            if class_name in ['truck', 'bus'] and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'bicycle':
                            if class_name == 'bicycle' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'motorcycle':
                            if class_name == 'motorcycle' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'traffic_light':
                            if class_name == 'traffic light' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'fire_hydrant':
                            if class_name == 'fire hydrant' and confidence > MIN_CONFIDENCE:
                                return True'''

new_section = '''            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)

                if results and len(results) > 0:
                    boxes = results[0].boxes

                    # Use class-specific confidence thresholds
                    # Lower for small/hard-to-detect objects, higher for common ones
                    CLASS_THRESHOLDS = {
                        'motorcycle': 0.25,      # Lower for small bikes
                        'bicycle': 0.25,         # Lower for small bikes
                        'car': 0.35,             # Medium for cars
                        'bus': 0.35,             # Medium for buses
                        'truck': 0.35,           # Medium for trucks
                        'traffic_light': 0.30,   # Lower for traffic lights
                        'fire_hydrant': 0.40,    # Higher to avoid false positives
                    }

                    threshold = CLASS_THRESHOLDS.get(target, 0.35)

                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])

                        # Only return True for reasonable detections
                        if confidence < threshold:
                            continue

                        # Debug output
                        if confidence > threshold * 0.5:  # Show near-threshold detections
                            print(f"      Detected {class_name} with {confidence:.2f} (threshold {threshold:.2f})")

                        # Relaxed mapping for vehicles
                        if target == 'car':
                            # Accept car, also trucks/buses with high confidence
                            if class_name in ['car', 'truck', 'bus'] and confidence > threshold:
                                return True
                        elif target == 'bus':
                            # Accept bus and truck
                            if class_name in ['bus', 'truck'] and confidence > threshold:
                                return True
                        elif target == 'truck':
                            # Accept truck and bus
                            if class_name in ['truck', 'bus'] and confidence > threshold:
                                return True
                        elif target == 'bicycle':
                            if class_name == 'bicycle' and confidence > threshold:
                                return True
                        elif target == 'motorcycle':
                            if class_name == 'motorcycle' and confidence > threshold:
                                return True
                        elif target == 'traffic_light':
                            if class_name == 'traffic light' and confidence > threshold:
                                return True
                        elif target == 'fire_hydrant':
                            if class_name == 'fire hydrant' and confidence > threshold:
                                return True'''

if old_section in content:
    content = content.replace(old_section, new_section)
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Successfully updated confidence thresholds")
else:
    print("❌ Could not find the exact section to replace")