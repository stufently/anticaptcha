"""reCAPTCHA v2/v3 solvers with stealth capabilities"""
import asyncio
import random
import time
from typing import Dict, Any, List
from pathlib import Path

# Optional: Playwright for browser automation
try:
    from app.utils.captcha_solver import BaseSolver
    from app.utils.browser import browser_manager
    from app.config import settings
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("⚠️ Playwright not installed. Browser automation unavailable, but Vision LLM works.")

from workers.classifiers.vision_llm import VisionLLMClassifier
import json
from workers.solvers.url_guard import validate_page_url
from workers.solvers.widget_page import check_browser_input, install_widget_page

# Optional: numpy for image processing
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("⚠️ NumPy not installed. Image processing limited, but Vision LLM works.")

# Optional: OpenCV for legacy YOLO detection methods
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("⚠️ OpenCV not installed. Legacy YOLO detection methods will not work, but Vision LLM will work fine.")

try:
    from ultralytics import YOLO
    from PIL import Image
    import io
    HAS_ML = True
except ImportError:
    HAS_ML = False
    YOLO = None


class RecaptchaV2Solver(BaseSolver):
    """Solve reCAPTCHA v2 with stealth and hybrid classification"""
    
    def __init__(self):
        super().__init__()
        self.yolo_model = None
        self.vision_classifier = None
    
    async def setup(self):
        """Setup solver and load Yolo model"""
        if HAS_ML:
            try:
                # Same lookup as YOLOClassifier: settings.models_dir,
                # recaptcha_custom.pt > yolov8s.pt > yolov8n.pt, never a download.
                from workers.classifiers.yolo import find_yolo_model
                model_path = find_yolo_model(settings.models_dir)
                print(f"✅ Loading YOLO model from {model_path}")
                self.yolo_model = YOLO(str(model_path))
                print("✅ Yolo model loaded for reCAPTCHA")
            except Exception as e:
                print(f"❌ reCAPTCHA: YOLO model not loaded ({type(e).__name__}: {e})")

        # Vision LLM is the primary tile classifier; it does not depend on YOLO.
        self.vision_classifier = VisionLLMClassifier()
        print("✅ Vision LLM classifier initialized")

    async def cleanup(self):
        """Cleanup resources"""
        pass
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v2 with stealth
        
        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com"
            }
        
        Returns:
            {"token": "..."}
        """
        site_key = input_data.get("site_key")
        page_url = input_data.get("page_url")
        
        if not site_key or not page_url:
            raise ValueError("Missing site_key or page_url")

        # SSRF guard before the browser is touched (shared by all URL solvers)
        page_url = await asyncio.to_thread(validate_page_url, page_url)

        # Create stealth page
        page = await browser_manager.new_page(stealth=True)
        
        try:
            # Navigate
            print(f"🌐 Navigating to {page_url}")
            await page.goto(page_url, timeout=settings.browser_timeout * 1000, wait_until='domcontentloaded')
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # Find reCAPTCHA iframe
            print("🔍 Finding reCAPTCHA widget...")
            await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=15000)
            
            # Click checkbox
            print("✅ Clicking checkbox...")
            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await checkbox_frame.locator('#recaptcha-anchor').click()
            await asyncio.sleep(random.uniform(3.0, 5.0))
            
            # Check for token
            token = await self._extract_token(page)
            
            if token:
                print(f"✅ Token received!")
                return {"token": token}
            
            # Check for image challenge
            print("⚠️ Image challenge detected, solving...")
            challenge_frame = page.frame_locator('iframe[src*="bframe"]')
            
            # Get challenge instruction
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"📋 Challenge: {instruction[:60]}")
            
            # Extract target keyword
            target = self._extract_target(instruction)
            if not target:
                raise ValueError(f"Unknown challenge: {instruction}")
            
            print(f"🎯 Target: {target}")
            
            # Solve image challenge with hybrid approach
            if self.yolo_model or HAS_ML:
                result = await self._solve_with_vision_llm(page, challenge_frame, target)  # Use Vision LLM instead of YOLO
                
                if result:
                    # Check for token
                    await asyncio.sleep(3)
                    token = await self._extract_token(page)
                    
                    if token:
                        print(f"✅ Challenge solved! Token: {token[:50]}...")
                        return {"token": token}
            
            raise RuntimeError("Could not solve image challenge")
        
        finally:
            await page.close()
    
    def _extract_target(self, instruction: str) -> str:
        """Extract target keyword from instruction"""
        instruction_lower = instruction.lower()
        keywords = [
            'car', 'bus', 'truck', 'bicycle', 'motorcycle',
            'traffic light', 'crosswalk', 'fire hydrant',
            'stairs', 'bridge', 'mountain', 'palm tree', 'chimney',
            'pedestrian', 'taxis'
        ]
        
        for keyword in keywords:
            if keyword in instruction_lower:
                # Normalize
                if keyword == 'traffic light':
                    return 'traffic_light'
                elif keyword == 'fire hydrant':
                    return 'fire_hydrant'
                elif keyword == 'palm tree':
                    return 'palm_tree'
                return keyword
        
        return None
    
    async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:
        """Solve using hybrid Yolo + heuristics approach"""
        print(f"🤖 Solving challenge (hybrid) for: {target}")
        
        # Get all image tiles
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        print(f"📸 Found {len(tiles)} images")
        
        # Classify each image
        selected = []
        for i, tile in enumerate(tiles):
            img = tile.locator('img')
            
            # Take screenshot
            screenshot = await img.screenshot()
            
            # Classify with hybrid approach
            should_select = await self._classify_image_hybrid(screenshot, target)
            
            if should_select:
                print(f"   Image {i+1}: ✅ SELECT")
                await tile.click()
                selected.append(i)
                await asyncio.sleep(random.uniform(0.5, 1.0))
            else:
                print(f"   Image {i+1}: ❌ Skip")
        
        print(f"✅ Selected {len(selected)} images")
        
        if selected:
            # Click verify
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True
        
        return False
    
    async def _solve_with_vision_llm(self, page, challenge_frame, target: str) -> bool:
        """
        Решает CAPTCHA с помощью одного вызова Vision LLM

        Подход конкурентов:
        1. Сделать screenshot всей CAPTCHA сетки
        2. Отправить в Vision LLM с инструкцией
        3. Получить индексы плиток для клика
        4. Кликнуть по этим плиткам

        Быстрее и точнее, чем YOLO!
        """
        print(f"🤖 Solving challenge with Vision LLM for: {target}")

        # Get challenge info
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        grid_size = len(tiles)
        print(f"📸 Found {grid_size} images")

        # Take screenshot of entire challenge
        try:
            challenge_screenshot = await challenge_frame.locator('.rc-imageselect-target').screenshot()
        except Exception:
            # Fallback: take screenshot of first tile
            challenge_screenshot = await tiles[0].locator('img').screenshot()

        # Call vision LLM for classification
        if self.vision_classifier:
            try:
                grid_type = "3x3" if grid_size == 9 else "4x4" if grid_size == 16 else "2x3"
                instruction = f"Select all tiles with {target.replace('_', ' ')}"

                indices = await self.vision_classifier.classify_tiles(
                    challenge_screenshot,
                    instruction,
                    grid_type
                )

                print(f"🎯 Vision LLM selected {len(indices)} tiles: {indices}")

                # Check if classification was successful
                # (Claude's finding #3 - don't click verify on empty/error)
                if not indices and len(indices) == 0:
                    # Check if this is an error or legitimate "no tiles match"
                    # For now, assume it's legitimate and continue
                    print(f"   No matching tiles found (this may be correct)")

                # Click selected tiles
                for idx in indices:
                    if 0 <= idx < len(tiles):
                        print(f"   Clicking tile {idx}")
                        await tiles[idx].click()
                        await asyncio.sleep(random.uniform(0.3, 0.7))

                # Click verify button
                verify_button = challenge_frame.locator('#recaptcha-verify-button')
                await verify_button.click()

                return True

            except RuntimeError as e:
                # Vision LLM failed - DON'T click verify with empty selection
                print(f"⚠️ Vision LLM failed: {e}")
                print(f"   Falling back to YOLO...")
                # Fall back to YOLO
                return await self._solve_image_challenge_hybrid(page, challenge_frame, target)
            except Exception as e:
                print(f"⚠️ Vision LLM unexpected error: {e}")
                # Fall back to YOLO
                return await self._solve_image_challenge_hybrid(page, challenge_frame, target)
        else:
            print("⚠️ Vision classifier not initialized, using YOLO")
            return await self._solve_image_challenge_hybrid(page, challenge_frame, target)

    async def _classify_image_hybrid(self, image_bytes: bytes, target: str) -> bool:
        """Hybrid classification: Yolo for COCO, heuristics for others"""
        try:
            # Open image
            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)
            
            # COCO classes - use Yolo with higher confidence
            coco_targets = ['car', 'bus', 'truck', 'bicycle', 'motorcycle', 'traffic_light', 'fire_hydrant']
            
            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)
                
                if results and len(results) > 0:
                    boxes = results[0].boxes
                    
                    # Use higher confidence threshold to reduce false positives
                    MIN_CONFIDENCE = 0.5  # Raised from 0.3
                    
                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])
                        
                        # Only return True for high-confidence detections
                        if confidence < MIN_CONFIDENCE:
                            continue
                        
                        # Strict mapping
                        if target == 'car':
                            # Only car, not trucks or buses
                            if class_name == 'car' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'bus':
                            if class_name == 'bus' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'truck':
                            if class_name == 'truck' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'bicycle':
                            if class_name == 'bicycle' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'motorcycle':
                            if class_name == 'motorcycle' and confidence > MIN_CONFIDENCE:
                                return True
                        elif target == 'traffic_light':
                            # Be very strict for traffic lights
                            if class_name == 'traffic light' and confidence > 0.6:
                                return True
                        elif target == 'fire_hydrant':
                            # Be very strict for fire hydrants
                            if class_name == 'fire hydrant' and confidence > 0.6:
                                return True
            
            # Heuristics for non-COCO classes
            elif target == 'crosswalk':
                return self._detect_crosswalk(img_array)
            elif target == 'stairs':
                return self._detect_stairs(img_array)
            elif target == 'bridge':
                return self._detect_bridge(img_array)
            elif target == 'mountain':
                return self._detect_mountain(img_array)
            elif target == 'palm_tree':
                return self._detect_palm_tree(img_array)
            
            # Unknown class - conservatively return False
            return False
        
        except Exception as e:
            print(f"      ⚠️ Classification error: {e}")
            return False
    
    def _detect_crosswalk(self, img_array: np.ndarray) -> bool:
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
        except Exception:
            return False
        
    
    def _detect_stairs(self, img_array: np.ndarray) -> bool:
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
        except Exception:
            return False
    
    def _detect_bridge(self, img_array: np.ndarray) -> bool:
        """Detect bridge (arch/horizontal structure)"""
        # Simple: check for horizontal structure in upper part
        try:
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Upper third
            upper = gray[:gray.shape[0]//3, :]
            
            # Check for continuous structure
            return np.std(upper) > 30
        except Exception:
            return False
    
    def _detect_mountain(self, img_array: np.ndarray) -> bool:
        """Detect mountain (triangular shape, natural colors)"""
        try:
            # Check for triangular/pointed shape in upper region
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Check variance (mountains have varied terrain)
            return np.std(gray) > 40
        except Exception:
            return False
    
    def _detect_palm_tree(self, img_array: np.ndarray) -> bool:
        """Detect palm tree (green color at top)"""
        try:
            if len(img_array.shape) == 3:
                # Check for green in upper region
                upper = img_array[:img_array.shape[0]//2, :, :]
                
                # Green channel should be dominant
                green_ratio = np.sum(upper[:, :, 1] > upper[:, :, 0] + 20) / upper[:, :, 1].size
                
                return green_ratio > 0.2
            return False
        except Exception:
            return False
    
    async def _extract_token(self, page) -> str:
        """Extract reCAPTCHA token"""
        try:
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            return token if token and len(token) > 10 else None
        except Exception:
            return None


class RecaptchaV3Solver(BaseSolver):
    """Solve reCAPTCHA v3 (invisible)"""

    # grecaptcha is defined by the page's own api.js, by the widget page, or by
    # the script this solver injects; execute() must not be called before then.
    EXECUTE_PRESENT_JS = (
        '() => typeof grecaptcha !== "undefined" && typeof grecaptcha.execute === "function"'
    )
    PAGE_SCRIPT_WAIT = 5    # seconds to let a page-provided api.js define grecaptcha
    INJECT_TIMEOUT = 15     # add_script_tag and the wait after it, under one bound
    EXECUTE_TIMEOUT = 20    # grecaptcha.ready + grecaptcha.execute
    POLL_INTERVAL = 0.25

    def __init__(self):
        super().__init__()

    async def setup(self):
        """Setup solver"""
        pass

    async def cleanup(self):
        """Cleanup resources"""
        pass

    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v3

        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com",
                "action": "submit",               # optional
                "render_mode": "page" | "widget"  # optional, default "page"
            }

        Returns:
            {"token": "..."}
        """
        site_key, page_url, render_mode = check_browser_input(input_data)
        action = input_data.get("action", "submit")

        # SSRF guard before the browser is touched (shared by all URL solvers)
        page_url = await asyncio.to_thread(validate_page_url, page_url)

        page = await browser_manager.new_page()

        try:
            token = await self._token_from(page, page_url, site_key, action, render_mode)
            return {"token": token}
        finally:
            await page.close()

    async def _token_from(
        self, page, page_url: str, site_key: str, action: str, render_mode: str
    ) -> str:
        """Load the page, make sure grecaptcha is there, then execute.

        Every step that talks to the network or to page JavaScript is bounded:
        an unresponsive Google endpoint used to hang the worker until its own
        task timeout, with no clue in the error message about which step stalled.
        """
        if render_mode == "widget":
            await install_widget_page(page, page_url, "recaptcha_v3", site_key)

        await page.goto(page_url, timeout=settings.browser_timeout * 1000)

        # A page that loads api.js itself needs no second copy — two grecaptcha
        # instances shadow each other — so give the page's script a moment first.
        await self._wait_for_execute(page, self.PAGE_SCRIPT_WAIT)

        if not await self._has_execute(page):
            try:
                injected = await asyncio.wait_for(
                    self._inject_api(page, site_key), self.INJECT_TIMEOUT
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "reCAPTCHA v3: api.js did not define grecaptcha.execute within 15s"
                ) from None
            except Exception as exc:
                raise RuntimeError(
                    f"reCAPTCHA v3: api.js injection failed ({type(exc).__name__})"
                ) from None
            if not injected:
                raise RuntimeError(
                    "reCAPTCHA v3: api.js loaded but grecaptcha.execute is missing"
                )

        try:
            token = await asyncio.wait_for(
                self._execute(page, site_key, action), self.EXECUTE_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise RuntimeError("reCAPTCHA v3: grecaptcha.execute timed out after 20s") from None
        except Exception as exc:
            # type name only: a Playwright error text is a stack dump, and the
            # worker log does not need one to say which step failed
            raise RuntimeError(
                f"reCAPTCHA v3: grecaptcha.execute failed ({type(exc).__name__})"
            ) from None

        if not token or not isinstance(token, str):
            raise RuntimeError("reCAPTCHA v3: grecaptcha.execute returned no token")
        return token

    async def _has_execute(self, page) -> bool:
        """True when grecaptcha.execute can be called on this page right now."""
        try:
            return bool(await page.evaluate(self.EXECUTE_PRESENT_JS))
        except Exception:
            return False

    async def _wait_for_execute(self, page, timeout: float) -> bool:
        """Poll for grecaptcha.execute for up to `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            if await self._has_execute(page):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _inject_api(self, page, site_key: str) -> bool:
        """Add Google's api.js and wait for it to define execute.

        Both steps belong under the caller's single bound: add_script_tag waits
        for the script itself and hangs forever when that load stalls.
        """
        await page.add_script_tag(url="https://www.google.com/recaptcha/api.js?render=" + site_key)
        return await self._wait_for_execute(page, self.INJECT_TIMEOUT)

    async def _execute(self, page, site_key: str, action: str) -> str:
        """grecaptcha.ready + execute as one promise, bounded by the caller."""
        return await page.evaluate('''
            async (args) => new Promise((resolve, reject) => {
                grecaptcha.ready(() => {
                    grecaptcha.execute(args.site_key, {action: args.action}).then(resolve, reject);
                });
            })
        ''', {"site_key": site_key, "action": action})
