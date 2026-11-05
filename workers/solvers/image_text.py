"""Image-to-text CAPTCHA solver using OCR"""
from typing import Dict, Any
import base64
import io
from app.utils.captcha_solver import BaseSolver


class ImageTextSolver(BaseSolver):
    """Solve text-based CAPTCHA using OCR"""
    
    def __init__(self):
        super().__init__()
        self.reader = None
    
    async def setup(self):
        """Initialize OCR model"""
        try:
            import easyocr
            import cv2
            import numpy as np
            self.reader = easyocr.Reader(['en'], gpu=False)
            self.cv2 = cv2
            self.np = np
            print("✅ EasyOCR initialized")
        except ImportError as e:
            print(f"⚠️ OCR dependencies not installed: {e}")
            print("   Install with: pip install easyocr opencv-python numpy")
            self.reader = None
            self.cv2 = None
            self.np = None
    
    async def cleanup(self):
        """Cleanup resources"""
        self.reader = None
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve image-to-text CAPTCHA
        
        Args:
            input_data: {
                "image": "base64_encoded_image"
            }
        
        Returns:
            {"text": "..."}
        """
        if self.reader is None:
            raise RuntimeError("OCR model not available. Install easyocr, opencv-python, and numpy.")
        
        image_base64 = input_data.get("image")
        
        if not image_base64:
            raise ValueError("Missing image data")
        
        # Decode image
        image_bytes = base64.b64decode(image_base64)
        
        # Preprocess image
        processed_image = self._preprocess_image(image_bytes)
        
        # Apply OCR
        result = self.reader.readtext(processed_image)
        
        # Extract text
        if result:
            text = ' '.join([r[1] for r in result]).strip()
            return {"text": text}
        
        return {"text": ""}
    
    def _preprocess_image(self, image_bytes: bytes):
        """
        Preprocess CAPTCHA image for better OCR results
        
        Steps:
        1. Decode image
        2. Convert to grayscale
        3. Remove noise
        4. Apply threshold
        5. Morphological operations
        """
        cv2 = self.cv2
        np = self.np
        
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise ValueError("Failed to decode image")
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Noise removal
        denoised = cv2.medianBlur(gray, 3)
        
        # Adaptive threshold
        thresh = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2
        )
        
        # Morphological operations to connect broken text
        kernel = np.ones((2, 2), np.uint8)
        morphed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        return morphed