#!/usr/bin/env python3
"""Apply all improvements to recaptcha.py cleanly"""

# Read file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# 1. Add imports
if 'from pathlib import Path' not in content:
    content = content.replace(
        'from typing import Dict, Any, List\nfrom app.utils.captcha_solver import BaseSolver',
        'from typing import Dict, Any, List\nfrom pathlib import Path\nfrom app.utils.captcha_solver import BaseSolver'
    )

if 'import cv2' not in content:
    content = content.replace(
        'import asyncio\nimport random',
        'import asyncio\nimport random\nimport cv2'
    )

# 2. Update setup to use custom model
setup_old = '''        if HAS_ML:
            try:
                # Use detection model
                self.yolo_model = YOLO('yolov8n.pt')
                print("✅ Yolo model loaded for reCAPTCHA")
            except Exception as e:
                print(f"⚠️ Could not load Yolo: {e}")'''

setup_new = '''        if HAS_ML:
            try:
                # Load larger model if available (YOLOv8s more accurate than YOLOv8n)
                large_model = Path('/app/data/yolov8s.pt')
                small_model = Path('/app/data/yolov8n.pt')
                custom_model = Path('/app/runs/detect/recaptcha_custom/weights/best.pt')
                
                if large_model.exists():
                    print(f"✅ Loading YOLOv8s (larger, more accurate)")
                    self.yolo_model = YOLO(str(large_model))
                elif small_model.exists():
                    print(f"✅ Loading YOLOv8n")
                    self.yolo_model = YOLO(str(small_model))
                else:
                    self.yolo_model = YOLO('yolov8n.pt')
                
                # Also load custom model for specific classes
                if custom_model.exists():
                    print(f"✅ Loading custom trained model")
                    self.custom_model = YOLO(str(custom_model))
                else:
                    self.custom_model = None
                
                print("✅ Yolo models loaded for reCAPTCHA")
            except Exception as e:
                print(f"⚠️ Could not load Yolo: {e}")'''

content = content.replace(setup_old, setup_new)

# 3. Update __init__ to add custom_model attribute
init_old = '''    def __init__(self):
        super().__init__()
        self.yolo_model = None'''

init_new = '''    def __init__(self):
        super().__init__()
        self.yolo_model = None
        self.custom_model = None'''

content = content.replace(init_old, init_new)

# 4. Replace _detect_crosswalk with OpenCV version
crosswalk_pattern = '''    def _detect_crosswalk\(self, img_array: np\.ndarray\) -> bool:.*?return False'''
crosswalk_replacement = '''    def _detect_crosswalk(self, img_array: np.ndarray) -> bool:
        """Detect crosswalk using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            # Edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            
            # Detect horizontal lines
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, 
                                    minLineLength=30, maxLineGap=10)
            
            if lines is not None:
                horizontal_lines = 0
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    if abs(y2 - y1) < 20 and abs(x2 - x1) > 30:
                        horizontal_lines += 1
                
                if horizontal_lines >= 3:
                    return True
            
            # Check for striped pattern
            height = gray.shape[0]
            bands = 10
            band_height = height // bands
            
            band_means = []
            for i in range(bands):
                band = gray[i*band_height:(i+1)*band_height, :]
                band_means.append(np.mean(band))
            
            variance = np.var(band_means)
            if variance > 500:
                return True
            
            return False
        except:
            return False'''

import re
content = re.sub(crosswalk_pattern, crosswalk_replacement, content, flags=re.DOTALL)

# 5. Replace _detect_stairs with OpenCV version
stairs_pattern = '''    def _detect_stairs\(self, img_array: np\.ndarray\) -> bool:.*?return False'''
stairs_replacement = '''    def _detect_stairs(self, img_array: np.ndarray) -> bool:
        """Detect stairs using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            # Edge detection
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Count horizontal edges
            horizontal_edges = 0
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > h * 3:
                    horizontal_edges += 1
            
            if horizontal_edges >= 3:
                return True
            
            # Check for horizontal lines
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=40,
                                    minLineLength=20, maxLineGap=5)
            
            if lines is not None:
                horizontal_count = 0
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                    if angle < 10 or angle > 170:
                        horizontal_count += 1
                
                if horizontal_count >= 4:
                    return True
            
            return False
        except:
            return False'''

content = re.sub(stairs_pattern, stairs_replacement, content, flags=re.DOTALL)

# Write back
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
    f.write(content)

print("✅ Applied all improvements cleanly")
print("   - Imports: Path, cv2")
print("   - YOLOv8s support")
print("   - Custom model loading")
print("   - OpenCV detection for crosswalk, stairs")