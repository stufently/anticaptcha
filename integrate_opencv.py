#!/usr/bin/env python3
"""Integrate OpenCV detection into recaptcha.py"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# 1. Add cv2 import
if 'import cv2' not in content:
    # Add after other imports
    content = content.replace(
        'import asyncio\nimport random',
        'import asyncio\nimport random\nimport cv2'
    )
    print("✅ Added cv2 import")

# 2. Replace _detect_crosswalk method
old_crosswalk = '''    def _detect_crosswalk(self, img_array: np.ndarray) -> bool:
        """Detect crosswalk (zebra stripes) - improved"""
        try:
            if len(img_array.shape) == 3:
                # Convert to grayscale
                gray = np.mean(img_array, axis=2)
            else:
                gray = img_array

            mean = np.mean(gray)

            # Crosswalk has distinctive white stripes on dark background
            # Check for high contrast pattern

            # 1. White stripes (significantly brighter than mean)
            white_pixels = gray > mean + 40
            white_ratio = np.sum(white_pixels) / gray.size

            # 2. Dark background (significantly darker than mean)
            dark_pixels = gray < mean - 20
            dark_ratio = np.sum(dark_pixels) / gray.size

            # 3. Check for striped pattern (alternating)
            # Look for regular horizontal or vertical patterns
            horizontal_variance = np.var(np.sum(white_pixels, axis=1))
            vertical_variance = np.var(np.sum(white_pixels, axis=0))

            # Crosswalk should have:
            # - Moderate white ratio (15-40%)
            # - Significant dark background
            # - Regular striped pattern

            if 0.15 < white_ratio < 0.40 and dark_ratio > 0.3:
                # Check for pattern regularity
                if horizontal_variance > 1000 or vertical_variance > 1000:
                    return True

            return False

        except Exception as e:
            print(f"      ⚠️ Crosswalk detection error: {e}")
            return False'''

new_crosswalk = '''    def _detect_crosswalk(self, img_array: np.ndarray) -> bool:
        """Detect crosswalk using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            # Apply edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            
            # Detect lines using Hough Transform
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, 
                                    minLineLength=30, maxLineGap=10)
            
            if lines is not None:
                # Check for horizontal lines (crosswalk stripes)
                horizontal_lines = 0
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    # Check if line is horizontal (y coordinates similar)
                    if abs(y2 - y1) < 20 and abs(x2 - x1) > 30:
                        horizontal_lines += 1
                
                # Crosswalk should have multiple parallel horizontal lines
                if horizontal_lines >= 3:
                    return True
            
            # Also check for high contrast stripes
            height = gray.shape[0]
            bands = 10
            band_height = height // bands
            
            band_means = []
            for i in range(bands):
                band = gray[i*band_height:(i+1)*band_height, :]
                band_means.append(np.mean(band))
            
            # Check for alternating bright/dark pattern
            variance = np.var(band_means)
            if variance > 500:  # High variance indicates stripes
                return True
            
            return False
        except:
            return False'''

if old_crosswalk in content:
    content = content.replace(old_crosswalk, new_crosswalk)
    print("✅ Replaced _detect_crosswalk with OpenCV version")
else:
    print("⚠️ Could not find old _detect_crosswalk")

# 3. Replace _detect_stairs method
old_stairs = '''    def _detect_stairs(self, img_array: np.ndarray) -> bool:
        """Detect stairs (horizontal lines)"""
        try:
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Detect strong horizontal edges
            gradient = np.abs(np.diff(gray, axis=1))
            edge_ratio = np.sum(gradient > 50) / gray.size
            
            return edge_ratio > 0.08
        except:
            return False'''

new_stairs = '''    def _detect_stairs(self, img_array: np.ndarray) -> bool:
        """Detect stairs using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            # Detect edges
            edges = cv2.Canny(gray, 50, 150)
            
            # Find contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Stairs have multiple horizontal edges
            horizontal_edges = 0
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                # Check if it's a horizontal edge (width >> height)
                if w > h * 3:
                    horizontal_edges += 1
            
            # Stairs should have multiple horizontal edges
            if horizontal_edges >= 3:
                return True
            
            # Also check for regular horizontal lines
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=40,
                                    minLineLength=20, maxLineGap=5)
            
            if lines is not None:
                horizontal_count = 0
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                    if angle < 10 or angle > 170:  # Horizontal
                        horizontal_count += 1
                
                if horizontal_count >= 4:
                    return True
            
            return False
        except:
            return False'''

if old_stairs in content:
    content = content.replace(old_stairs, new_stairs)
    print("✅ Replaced _detect_stairs with OpenCV version")
else:
    print("⚠️ Could not find old _detect_stairs")

# Write back
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
    f.write(content)

print("\n✅ OpenCV detection integrated into recaptcha.py")