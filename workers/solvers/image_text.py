"""Image-to-text CAPTCHA solver using OCR"""
from typing import Dict, Any
import asyncio
import base64
import io
from concurrent.futures import ThreadPoolExecutor
from app.utils.captcha_solver import BaseSolver


class ImageTextSolver(BaseSolver):
    """Solve text-based CAPTCHA using OCR"""
    
    def __init__(self):
        super().__init__()
        self.reader = None
        # Own single-thread executor, not the shared default one: easyocr.Reader
        # is not safe for concurrent calls, so OCR jobs are serialized here, and
        # a hung OCR only queues image_text jobs instead of exhausting the pool
        # that other solvers use (asyncio.to_thread for url_guard etc.).
        self._ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
    
    async def setup(self):
        """Initialize OCR model"""
        try:
            import easyocr
            import cv2
            import numpy as np
            # Model dirs come from easyocr itself ($EASYOCR_MODULE_PATH/model and
            # /user_network), exactly as in the Dockerfile warm-up. No downloads at
            # runtime: missing weights must fail loudly, not hit the internet.
            # quantize=False: easyocr's default dynamic-quantized LSTM runs
            # torch kernels that need AVX2/FMA; on older CPUs (e.g. Ivy Bridge,
            # AVX only) the worker dies with SIGILL (exit 132) on the first
            # image_text task. The float model works everywhere.
            self.reader = easyocr.Reader(
                ['en'], gpu=False, download_enabled=False, quantize=False
            )
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
        self._ocr_executor.shutdown(wait=False, cancel_futures=True)
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
        
        # Decode + OCR are synchronous and CPU-heavy: run them off the event
        # loop so the worker's task timeout keeps working. On timeout the
        # future is cancelled: a job that has not started never runs, a running
        # one finishes and its result is dropped; the task stays failed.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ocr_executor, self._ocr, image_base64)

    def _ocr(self, image_base64: str) -> Dict[str, Any]:
        image_bytes = base64.b64decode(image_base64)
        processed_image = self._preprocess_image(image_bytes)
        result = self.reader.readtext(processed_image)
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