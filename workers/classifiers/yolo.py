"""YOLO-based CAPTCHA classifier for fast image detection"""

import asyncio
import json
import tempfile
from typing import List, Optional, Tuple
from pathlib import Path

# Optional dependencies
try:
    from ultralytics import YOLO
    import numpy as np
    from PIL import Image
    import io
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False
    YOLO = None
    print("⚠️ YOLO not installed. Install with: pip install ultralytics")


YOLO_MODEL_PRIORITY = (
    'recaptcha_custom.pt',  # Custom trained
    'yolov8s.pt',  # YOLOv8 small
    'yolov8n.pt',  # YOLOv8 nano
)


def find_yolo_model(models_dir) -> Path:
    """Return the first existing YOLO checkpoint in models_dir.

    Priority: recaptcha_custom.pt > yolov8s.pt > yolov8n.pt. Raises
    FileNotFoundError instead of letting ultralytics download weights
    from the internet at runtime.
    """
    models_dir = Path(models_dir)
    possible_paths = [models_dir / name for name in YOLO_MODEL_PRIORITY]
    for path in possible_paths:
        if path.exists():
            print(f"✅ Found model: {path}")
            return path
    raise FileNotFoundError(
        f"No YOLO model found in {models_dir}. "
        f"Expected one of: {[str(p) for p in possible_paths]}. "
        f"Download models or set ANTICAPTCHA_MODELS_DIR correctly."
    )


class YOLOClassifier:
    """
    YOLO-based classifier for CAPTCHA images

    Fast, offline, free alternative to Vision LLM.
    Works only with image CAPTCHA (reCAPTCHA, hCaptcha, etc.)
    """

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize YOLO classifier

        Args:
            model_path: Path to YOLO model (default: auto-detect)
        """
        self.model = None
        self.model_path = model_path
        self._initialized = False

        if not HAS_YOLO:
            raise ImportError("YOLO not installed. Install with: pip install ultralytics")

    def _load_model(self):
        """Load YOLO model lazily"""
        if self._initialized:
            return

        try:
            from app.config import settings
            
            # Try to find model
            if self.model_path:
                model_path = Path(self.model_path)
            else:
                model_path = find_yolo_model(settings.models_dir)

            print(f"✅ Loading YOLO model from {model_path}")
            self.model = YOLO(str(model_path))
            self._initialized = True

        except Exception as e:
            print(f"❌ Error loading YOLO model: {e}")
            raise

    async def classify_tiles(
        self,
        image_data: bytes,
        target: str,
        grid_size: str = "3x3",
        confidence_threshold: float = 0.5
    ) -> List[int]:
        """
        Classify CAPTCHA tiles using YOLO

        Args:
            image_data: Image bytes
            target: What to look for (e.g., "cars", "crosswalks")
            grid_size: Grid layout (e.g., "3x3", "4x4")
            confidence_threshold: Minimum confidence for detection

        Returns:
            List of tile indices containing target objects
        """
        try:
            self._load_model()

            # Convert bytes to image
            image = Image.open(io.BytesIO(image_data))

            # Determine grid
            if "x" in grid_size:
                rows, cols = map(int, grid_size.split("x"))
            else:
                rows, cols = 3, 3

            tile_width = image.width // cols
            tile_height = image.height // rows

            # Run YOLO on full image
            results = self.model(image, verbose=False)

            # Extract detections
            detections = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    # Get class and confidence
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])

                    if confidence >= confidence_threshold:
                        # Get bounding box
                        x1, y1, x2, y2 = box.xyxy[0].tolist()

                        # Map to tile
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2

                        tile_col = int(center_x // tile_width)
                        tile_row = int(center_y // tile_height)

                        if 0 <= tile_col < cols and 0 <= tile_row < rows:
                            tile_index = tile_row * cols + tile_col

                            detections.append({
                                "tile": tile_index,
                                "class": class_name,
                                "confidence": confidence,
                                "bbox": [x1, y1, x2, y2]
                            })

            # Filter by target
            target_keywords = self._get_target_keywords(target)
            matching_tiles = set()

            for det in detections:
                if any(kw in det["class"].lower() for kw in target_keywords):
                    matching_tiles.add(det["tile"])

            # If no matches, try to use center tile detection
            if not matching_tiles:
                # Use center-based detection
                for det in detections:
                    if det["confidence"] >= confidence_threshold:
                        matching_tiles.add(det["tile"])

            result = sorted(list(matching_tiles))
            print(f"   YOLO detected {len(detections)} objects, {len(result)} tiles match '{target}'")

            return result

        except Exception as e:
            print(f"❌ YOLO classification error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _get_target_keywords(self, target: str) -> List[str]:
        """Get keywords for target object"""
        target = target.lower().strip()

        # Mapping of targets to YOLO classes
        keyword_map = {
            "car": ["car", "truck", "bus", "vehicle", "automobile"],
            "cars": ["car", "truck", "bus", "vehicle", "automobile"],
            "crosswalk": ["crosswalk", "zebra", "pedestrian"],
            "bus": ["bus", "vehicle"],
            "truck": ["truck", "vehicle"],
            "traffic light": ["traffic light", "traffic light"],
            "fire hydrant": ["fire hydrant", "hydrant"],
            "stop sign": ["stop sign", "sign"],
            "parking meter": ["parking meter", "meter"],
            "bench": ["bench", "seat"],
            "bicycle": ["bicycle", "bike", "cycle"],
            "motorcycle": ["motorcycle", "motorbike", "bike"],
            "airplane": ["airplane", "plane", "aircraft"],
            "boat": ["boat", "ship", "vessel"],
            "train": ["train", "railway"],
            "stairs": ["stairs", "steps", "staircase"],
            "bridge": ["bridge", "overpass"],
            "mountain": ["mountain", "hill", "peak"],
            "tunnel": ["tunnel", "underpass"],
            "chimney": ["chimney", "smokestack"],
            "palm tree": ["palm tree", "palm", "tree"],
        }

        # Find matching keywords
        for key, keywords in keyword_map.items():
            if key in target or target in key:
                return keywords

        # Default: use target as keyword
        return [target]

    def detect_objects(
        self,
        image_data: bytes,
        confidence_threshold: float = 0.5
    ) -> List[dict]:
        """
        Detect all objects in image

        Args:
            image_data: Image bytes
            confidence_threshold: Minimum confidence

        Returns:
            List of detected objects
        """
        try:
            self._load_model()

            image = Image.open(io.BytesIO(image_data))
            results = self.model(image, verbose=False)

            objects = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])

                    if confidence >= confidence_threshold:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()

                        objects.append({
                            "class": class_name,
                            "confidence": confidence,
                            "bbox": [x1, y1, x2, y2]
                        })

            return objects

        except Exception as e:
            print(f"❌ YOLO detection error: {e}")
            return []

    def cleanup(self):
        """Cleanup resources"""
        if self.model:
            # YOLO doesn't need explicit cleanup
            pass


class HybridClassifier:
    """
    Hybrid classifier: YOLO (fast) + Vision LLM fallback (accurate)

    Strategy:
    1. Try YOLO first (free, fast, offline)
    2. If confidence low → Vision LLM (paid, accurate, online)
    """

    def __init__(self, yolo_threshold: float = 0.7, confidence_threshold: float = 0.5):
        """
        Initialize hybrid classifier

        Args:
            yolo_threshold: Use YOLO if confidence above this
            confidence_threshold: Minimum confidence for detections
        """
        self.yolo_threshold = yolo_threshold
        self.confidence_threshold = confidence_threshold

        self.yolo_classifier = None
        self.vision_classifier = None

        # Lazy loading
        self._yolo_initialized = False
        self._vision_initialized = False

    def _init_yolo(self):
        """Initialize YOLO classifier"""
        if self._yolo_initialized:
            return

        try:
            if HAS_YOLO:
                self.yolo_classifier = YOLOClassifier()
                self._yolo_initialized = True
                print("✅ YOLO classifier initialized")
        except Exception as e:
            print(f"⚠️ YOLO initialization failed: {e}")

    def _init_vision(self):
        """Initialize Vision LLM classifier"""
        if self._vision_initialized:
            return

        try:
            from workers.classifiers.vision_llm import VisionLLMClassifier
            self.vision_classifier = VisionLLMClassifier()
            self._vision_initialized = True
            print("✅ Vision LLM classifier initialized")
        except Exception as e:
            print(f"⚠️ Vision LLM initialization failed: {e}")

    async def classify_tiles(
        self,
        image_data: bytes,
        target: str,
        grid_size: str = "3x3"
    ) -> List[int]:
        """
        Classify tiles using hybrid approach

        Args:
            image_data: Image bytes
            target: What to look for
            grid_size: Grid layout

        Returns:
            List of tile indices
        """
        # Try YOLO first
        if HAS_YOLO:
            try:
                self._init_yolo()

                if self.yolo_classifier:
                    # Run YOLO
                    yolo_result = await self.yolo_classifier.classify_tiles(
                        image_data,
                        target,
                        grid_size,
                        self.confidence_threshold
                    )

                    # Check confidence
                    if yolo_result and len(yolo_result) > 0:
                        # YOLO found something - use it
                        print(f"✅ YOLO result: {yolo_result}")
                        return yolo_result
                    else:
                        print(f"⚠️ YOLO found nothing, falling back to Vision LLM")

            except Exception as e:
                print(f"⚠️ YOLO error, falling back to Vision LLM: {e}")

        # Fallback to Vision LLM
        try:
            self._init_vision()

            if self.vision_classifier:
                result = await self.vision_classifier.classify_tiles(
                    image_data,
                    target,
                    grid_size
                )
                print(f"✅ Vision LLM result: {result}")
                return result
            else:
                print("❌ No classifier available")
                return []

        except Exception as e:
            print(f"❌ Vision LLM error: {e}")
            return []

    def cleanup(self):
        """Cleanup resources"""
        if self.yolo_classifier:
            self.yolo_classifier.cleanup()
        if self.vision_classifier:
            self.vision_classifier.cleanup()


if __name__ == "__main__":
    # Test
    print("=" * 60)
    print("YOLO Classifier Test")
    print("=" * 60)

    if not HAS_YOLO:
        print("\n❌ YOLO not installed")
        print("Install with: pip install ultralytics")
    else:
        print("\n✅ YOLO available")

        # Test hybrid classifier
        classifier = HybridClassifier()

        print("\nClassifier ready")
        print("Strategy: YOLO (fast) → Vision LLM (accurate)")