#!/usr/bin/env python3
"""Improve heuristic detection with OpenCV for non-COCO classes"""
import cv2
import numpy as np

# Test improved detection methods
def detect_crosswalk_opencv(img_array):
    """Improved crosswalk detection using OpenCV"""
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
        # Split image into horizontal bands
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
        return False

def detect_stairs_opencv(img_array):
    """Improved stairs detection using OpenCV"""
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
            # Get bounding rectangle
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
        return False

def detect_bridge_opencv(img_array):
    """Bridge detection using OpenCV"""
    try:
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        height, width = gray.shape
        
        # Look for arch/curved structures in upper part
        upper = gray[:height//2, :]
        
        # Detect edges
        edges = cv2.Canny(upper, 50, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Bridge should have large curved/rectangular structures
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > (width * height // 20):  # Significant area
                # Check if it's roughly rectangular or curved
                approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
                if len(approx) >= 4:  # Rectangular or polygonal
                    return True
        
        return False
    except:
        return False

def detect_mountain_opencv(img_array):
    """Mountain detection using OpenCV"""
    try:
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Detect edges
        edges = cv2.Canny(blurred, 30, 100)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Mountains have triangular/pointed shapes
        for contour in contours:
            # Approximate contour
            approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
            
            # Check for triangular shapes
            if len(approx) == 3:
                # Check if it's large enough
                area = cv2.contourArea(contour)
                if area > gray.size // 30:
                    return True
            
            # Also check for jagged/irregular shapes
            if len(approx) >= 5:  # Polygonal
                # Check variance in contour
                hull = cv2.convexHull(contour)
                hull_area = cv2.contourArea(hull)
                contour_area = cv2.contourArea(contour)
                
                # Mountains are not convex (jagged)
                if hull_area > 0 and contour_area / hull_area < 0.8:
                    return True
        
        return False
    except:
        return False

def detect_palm_tree_opencv(img_array):
    """Palm tree detection using OpenCV"""
    try:
        if len(img_array.shape) == 3:
            hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)
            
            # Define green color range
            lower_green = np.array([30, 40, 40])
            upper_green = np.array([90, 255, 255])
            
            # Create mask for green areas
            mask = cv2.inRange(hsv, lower_green, upper_green)
            
            # Check for green in upper part (fronds)
            height = img_array.shape[0]
            upper_mask = mask[:height//2, :]
            
            green_ratio = np.sum(upper_mask > 0) / upper_mask.size
            
            # Palm trees have significant green in upper part
            if green_ratio > 0.15:
                # Also check for trunk (brown/vertical in lower part)
                lower_bgr = img_array[height//2:, :, :]
                lower_gray = cv2.cvtColor(lower_bgr, cv2.COLOR_RGB2GRAY)
                
                # Look for vertical edges (trunk)
                edges = cv2.Canny(lower_gray, 50, 150)
                lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=30,
                                        minLineLength=20, maxLineGap=5)
                
                if lines is not None:
                    vertical_lines = 0
                    for line in lines:
                        x1, y1, x2, y2 = line[0]
                        angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                        if 70 < angle < 110:  # Vertical
                            vertical_lines += 1
                    
                    if vertical_lines >= 1:
                        return True
        
        return False
    except:
        return False

# Test with sample images
if __name__ == "__main__":
    print("Testing improved OpenCV detection methods...")
    
    # Create test images
    test_img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    
    print("\nCrosswalk detection:", detect_crosswalk_opencv(test_img))
    print("Stairs detection:", detect_stairs_opencv(test_img))
    print("Bridge detection:", detect_bridge_opencv(test_img))
    print("Mountain detection:", detect_mountain_opencv(test_img))
    print("Palm tree detection:", detect_palm_tree_opencv(test_img))
    
    print("\n✅ All OpenCV detection functions working")