#!/usr/bin/env python3
"""Replace _detect_crosswalk with OpenCV version and add other methods"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    lines = f.readlines()

# Find and replace _detect_crosswalk (lines 381-431, 51 lines total)
crosswalk_start = 380  # 0-indexed
crosswalk_end = 431

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
                    if abs(y2 - y1) < 20 and abs(x2 - x1) > 30:
                        horizontal_lines += 1
                
                if horizontal_lines >= 3:
                    return True
            
            # Check for high contrast stripes
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
            return False

'''

# Replace crosswalk
lines[crosswalk_start:crosswalk_end+1] = [new_crosswalk]

# Find where to insert bridge, mountain, palm_tree methods
# After _detect_stairs
stairs_end = None
for i in range(len(lines)-1, -1, -1):
    if 'def _detect_palm_tree' in lines[i]:
        stairs_end = i
        break

if stairs_end is None:
    # Find _detect_bridge
    for i in range(len(lines)):
        if 'def _detect_bridge' in lines[i]:
            stairs_end = i
            break

# Add improved methods after palm_tree
new_methods = '''
    def _detect_bridge(self, img_array: np.ndarray) -> bool:
        """Bridge detection using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            height, width = gray.shape
            
            # Look for arch/curved structures in upper part
            upper = gray[:height//2, :]
            
            edges = cv2.Canny(upper, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > (width * height // 20):
                    approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
                    if len(approx) >= 4:
                        return True
            
            return False
        except:
            return False

    def _detect_mountain(self, img_array: np.ndarray) -> bool:
        """Mountain detection using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array
            
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 30, 100)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
                
                if len(approx) == 3:
                    area = cv2.contourArea(contour)
                    if area > gray.size // 30:
                        return True
                
                if len(approx) >= 5:
                    hull = cv2.convexHull(contour)
                    hull_area = cv2.contourArea(hull)
                    contour_area = cv2.contourArea(contour)
                    
                    if hull_area > 0 and contour_area / hull_area < 0.8:
                        return True
            
            return False
        except:
            return False

    def _detect_palm_tree(self, img_array: np.ndarray) -> bool:
        """Palm tree detection using OpenCV"""
        try:
            if len(img_array.shape) == 3:
                hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)
                
                lower_green = np.array([30, 40, 40])
                upper_green = np.array([90, 255, 255])
                
                mask = cv2.inRange(hsv, lower_green, upper_green)
                
                height = img_array.shape[0]
                upper_mask = mask[:height//2, :]
                
                green_ratio = np.sum(upper_mask > 0) / upper_mask.size
                
                if green_ratio > 0.15:
                    lower_bgr = img_array[height//2:, :, :]
                    lower_gray = cv2.cvtColor(lower_bgr, cv2.COLOR_RGB2GRAY)
                    
                    edges = cv2.Canny(lower_gray, 50, 150)
                    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=30,
                                            minLineLength=20, maxLineGap=5)
                    
                    if lines is not None:
                        vertical_lines = 0
                        for line in lines:
                            x1, y1, x2, y2 = line[0]
                            angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                            if 70 < angle < 110:
                                vertical_lines += 1
                        
                        if vertical_lines >= 1:
                            return True
            
            return False
        except:
            return False
'''

if stairs_end:
    # Insert after existing palm_tree
    lines.insert(stairs_end+1, new_methods)
    print(f"✅ Inserted improved methods after line {stairs_end+1}")
else:
    print("⚠️ Could not find insertion point, appending to end")
    lines.append(new_methods)

# Write back
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
    f.writelines(lines)

print("✅ All OpenCV detection methods integrated")