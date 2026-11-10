"""Image-to-text CAPTCHA solver using OCR"""
from typing import Dict, Any, Tuple
import asyncio
import base64
import io
import sys
from concurrent.futures import ThreadPoolExecutor
from app.config import settings
from app.utils.captcha_solver import BaseSolver

# Formats Pillow and OpenCV agree on. A header-only size check is only sound
# when both readers parse the same dimensions: a JPEG 2000 file with two `ihdr`
# boxes is read by Pillow from the last one (32x32) and by OpenJPEG inside
# `cv2.imdecode` from the first one (2500x2000), so a 505-byte upload passes
# the limits and then explodes on decode. TIFF has the same IFD ambiguity.
ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "BMP"})


def _open_header(image_bytes: bytes):
    """Open an image for a header-only read, bypassing third-party patches.

    `ultralytics` (imported by the YOLO classifiers, so it is always loaded in
    the worker) replaces `PIL.Image.open` with a HEIF fallback that swallows
    the original error and raises `ModuleNotFoundError: No module named
    'pi_heif'` whenever that optional plugin is missing - it even tries to pip
    install it at runtime. A decompression bomb would then be reported as a
    merely "unsupported" image, so use the pristine Pillow opener when a patch
    is detected and keep the patched one otherwise.
    """
    from PIL import Image

    opener = Image.open
    patch_module_name = getattr(opener, "__module__", None)
    if patch_module_name not in (None, Image.__name__):
        patch_module = sys.modules.get(patch_module_name)
        pristine = getattr(patch_module, "_image_open", None)
        if callable(pristine):
            opener = pristine
    return opener(io.BytesIO(image_bytes))


def check_image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Reject oversized client images before a single pixel is decoded.

    Width and height come from the header only (`Image.open` without
    `load()`): a monochrome 20000x20000 PNG is ~1.2 MB on the wire (it fits
    the 5 MiB body limit) but ~4 GB once decoded and preprocessed, which the
    OOM killer takes out of the worker. Limits are read from `settings` at
    call time so they stay configurable per deployment.

    The header is only trustworthy for formats both readers parse identically
    (`ALLOWED_IMAGE_FORMATS`); anything else is rejected instead of measured.
    """
    from PIL import Image

    try:
        with _open_header(image_bytes) as header:
            width, height = header.size
            fmt = header.format
    except Image.DecompressionBombError as exc:
        raise ValueError(f"Image too large: {exc}") from None
    except Exception as exc:
        raise ValueError(
            f"Unsupported or corrupt image: {type(exc).__name__}: {exc}"
        ) from None

    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise ValueError(f"Unsupported image format: {fmt}")

    max_pixels = settings.max_image_pixels
    max_side = settings.max_image_side

    if width * height > max_pixels:
        raise ValueError(
            f"Image too large: {width}x{height} is {width * height} pixels, "
            f"the limit is {max_pixels}"
        )
    if max(width, height) > max_side:
        raise ValueError(
            f"Image too large: {width}x{height} exceeds the {max_side} pixel side limit"
        )
    return width, height


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
        1. Reject oversized images (header only, before any decode)
        2. Decode image
        3. Convert to grayscale
        4. Remove noise
        5. Apply threshold
        6. Morphological operations
        """
        check_image_dimensions(image_bytes)

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