#!/usr/bin/env python3
"""
Update solver to use custom trained model

Run this after training to update the solver configuration.
"""
import sys
from pathlib import Path

# Paths
SOLVER_FILE = Path('/app/workers/solvers/recaptcha.py')
CUSTOM_MODEL = Path('/app/runs/detect/recaptcha_custom/weights/best.pt')

print("🔄 Updating solver to use custom model...")
print(f"   Solver: {SOLVER_FILE}")
print(f"   Custom model: {CUSTOM_MODEL}")
print()

# Check if custom model exists
if not CUSTOM_MODEL.exists():
    print("❌ Custom model not found!")
    print("   Train the model first: python train_custom_yolo.py")
    sys.exit(1)

# Read solver file
with open(SOLVER_FILE, 'r') as f:
    content = f.read()

# Replace model loading
old_line = "self.yolo_model = YOLO('yolov8n.pt')"
new_line = f"self.yolo_model = YOLO('{str(CUSTOM_MODEL)}')"

if old_line in content:
    content = content.replace(old_line, new_line)

    # Write back
    with open(SOLVER_FILE, 'w') as f:
        f.write(content)

    print("✅ Solver updated to use custom model!")
    print()
    print("   Old: YOLO('yolov8n.pt')  # Pretrained COCO model")
    print(f"   New: YOLO('{str(CUSTOM_MODEL)}')  # Custom reCAPTCHA model")
    print()
    print("   Next step: Test on real CAPTCHAs")
    print("   python test_multiple_sites.py")
else:
    print("⚠️ Could not find model loading line in solver")
    print("   Manual update needed:")
    print(f"   Replace 'YOLO('yolov8n.pt')' with 'YOLO('{str(CUSTOM_MODEL)}')' in {SOLVER_FILE}")