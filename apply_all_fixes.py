#!/usr/bin/env python3
"""Apply all modifications to recaptcha.py correctly"""

# Read file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    lines = f.readlines()

# Find and replace sections
new_lines = []
for i, line in enumerate(lines):
    # Change 1: Use custom model first
    if 'local_model = Path' in line:
        # Replace the entire setup section
        new_lines.append('                # Try custom trained model first, then pretrained\n')
        new_lines.append('                custom_model = Path(\'/app/runs/detect/recaptcha_custom/weights/best.pt\')\n')
        new_lines.append('                pretrained_model = Path(\'/app/data/yolov8n.pt\')\n')
        new_lines.append('                \n')
        new_lines.append('                if custom_model.exists():\n')
        new_lines.append('                    print(f"✅ Loading custom trained model: {custom_model}")\n')
        new_lines.append('                    self.yolo_model = YOLO(str(custom_model))\n')
        new_lines.append('                    print("✅ Custom model loaded for reCAPTCHA (trained on synthetic data)")\n')
        new_lines.append('                elif pretrained_model.exists():\n')
        new_lines.append('                    print(f"✅ Loading local pretrained model: {pretrained_model}")\n')
        new_lines.append('                    self.yolo_model = YOLO(str(pretrained_model))\n')
        new_lines.append('                else:\n')
        new_lines.append('                    print("✅ Loading pretrained model (will download if needed)")\n')
        new_lines.append('                    self.yolo_model = YOLO(\'yolov8n.pt\')\n')
        # Skip next 9 lines (old code)
        for _ in range(9):
            i += 1
        continue
    
    # Change 2: Lower confidence threshold and add debug
    if 'MIN_CONFIDENCE = 0.5  # Higher threshold for accuracy' in line:
        new_lines.append('                    MIN_CONFIDENCE = 0.15  # Very low threshold to maximize detections\n')
        continue
    
    # Change 3: Add debug output after getting boxes
    if 'boxes = results[0].boxes' in line:
        new_lines.append(line)
        # Add debug
        new_lines.append('                    \n')
        new_lines.append('                    # Debug: show number of detections\n')
        new_lines.append('                    if len(boxes) > 0:\n')
        new_lines.append('                        print(f"      📦 Model detected {len(boxes)} objects")\n')
        continue
    
    # Change 4: Add debug for each detection
    if 'confidence = float(box.conf[0])' in line:
        new_lines.append(line)
        new_lines.append('                        # Debug: show each detection\n')
        new_lines.append('                        print(f"      - {class_name}: {confidence:.2f} (threshold: {MIN_CONFIDENCE:.2f})")\n')
        continue
    
    new_lines.append(line)

# Write back
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
    f.writelines(new_lines)

print("✅ Applied all modifications to recaptcha.py")
print(f"   - Custom model loading")
print(f"   - Confidence threshold: 0.15")
print(f"   - Debug output for detections")