"""reCAPTCHA v2/v3 solvers with stealth capabilities"""
import asyncio
import random
import time
from typing import Dict, Any, List, Optional
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


# --- reCAPTCHA v2 ---------------------------------------------------------
# The widget is split over two iframes: the checkbox lives in the "anchor"
# frame, the image challenge in the "bframe" one. Both are matched by URL
# because Google localises the title attribute.
CHECKBOX_FRAME = 'iframe[src*="anchor"]'
CHALLENGE_FRAME = 'iframe[src*="bframe"]'
CHECKBOX_ELEMENT = "#recaptcha-anchor"
VERIFY_BUTTON = "#recaptcha-verify-button"
TILE_WRAPPER = ".rc-image-tile-wrapper"
CHALLENGE_TARGET = ".rc-imageselect-target"
# The instruction sits in one of two containers depending on the challenge
# layout; the thing to select is the word Google emphasizes with <strong>.
CHALLENGE_DESC = ".rc-imageselect-desc-wrapper, .rc-imageselect-instructions"
CHALLENGE_STRONG = ".rc-imageselect-desc-wrapper strong, .rc-imageselect-instructions strong"
# A rejected round announces itself with one of these banners instead of a token.
CHALLENGE_ERRORS = (
    ".rc-imageselect-error-select-more",
    ".rc-imageselect-error-dynamic-more",
    ".rc-imageselect-incorrect-response",
)
# "Click verify once there are none left" marks a grid that refills itself.
DYNAMIC_MARKER = "none left"

TOKEN_JS = """() => {
    const el = document.getElementById('g-recaptcha-response');
    return el && el.value ? el.value : null;
}"""

FRAME_TIMEOUT_MS = 20000
CLICK_TIMEOUT_MS = 10000
CHECKBOX_TOKEN_TIMEOUT = 6   # seconds to poll for a token after the checkbox click
TOKEN_POLL_INTERVAL = 0.25

MAX_ROUNDS = 5
MAX_DYNAMIC_PASSES = 5


class RecaptchaV2Solver(BaseSolver):
    """Solve reCAPTCHA v2: checkbox first, then the image challenge in rounds.

    Google answers a datacenter IP with an image challenge almost always, and a
    challenge is rarely over after one verify: it comes back with a new grid, a
    "select more" banner, or tiles that refill as they are clicked. So the
    challenge is read and answered in a bounded loop of rounds.

    Every challenge helper takes a `root` — anything with a `.locator()` method:
    in production `page.frame_locator('iframe[src*="bframe"]')`, in the unit
    tests the page itself carrying a fake bframe DOM.
    """
    
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
        Solve reCAPTCHA v2

        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com",
                "render_mode": "page" | "widget"  # optional, default "page"
            }

        Returns:
            {"token": "..."}
        """
        site_key, page_url, render_mode = check_browser_input(input_data)

        # SSRF guard before the browser is touched (shared by all URL solvers)
        page_url = await asyncio.to_thread(validate_page_url, page_url)

        page = await browser_manager.new_page(stealth=True)

        try:
            if render_mode == "widget":
                # The client's page may be closed to this IP by a WAF (the public
                # demo pages answer 403 to datacenters) while Google's own
                # scripts stay reachable: serve the widget ourselves.
                await install_widget_page(page, page_url, "recaptcha_v2", site_key)

            print(f"🌐 reCAPTCHA v2: navigating to {page_url}")
            await page.goto(
                page_url,
                timeout=settings.browser_timeout * 1000,
                wait_until="domcontentloaded",
            )

            await page.wait_for_selector(CHECKBOX_FRAME, timeout=FRAME_TIMEOUT_MS)
            await page.frame_locator(CHECKBOX_FRAME).locator(CHECKBOX_ELEMENT).click(
                timeout=CLICK_TIMEOUT_MS
            )
            print("🖱️ reCAPTCHA v2: checkbox clicked, polling for the token")

            token = await self._poll_token(page, CHECKBOX_TOKEN_TIMEOUT)
            if token:
                # Google let the click through without a challenge. The log gets
                # the length only, never the token itself.
                print(f"✅ reCAPTCHA v2: token without a challenge ({len(token)} chars)")
                return {"token": token}

            await page.wait_for_selector(CHALLENGE_FRAME, timeout=FRAME_TIMEOUT_MS)
            print("⚠️ reCAPTCHA v2: image challenge detected, solving in rounds")
            token = await self._solve_rounds(page, page.frame_locator(CHALLENGE_FRAME))
            return {"token": token}

        finally:
            await page.close()

    async def _poll_token(self, page, timeout: float) -> Optional[str]:
        """Poll `#g-recaptcha-response` for up to `timeout` seconds."""
        deadline = time.monotonic() + timeout

        while True:
            token = await self._read_token(page)
            if token:
                return token
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(TOKEN_POLL_INTERVAL)

    async def _read_token(self, page) -> Optional[str]:
        """One token read off the page; None when there is no token yet."""
        try:
            return await page.evaluate(TOKEN_JS) or None
        except Exception:
            return None

    async def _solve_rounds(self, page, root) -> str:
        """Answer the challenge round after round until Google issues a token.

        One verify is rarely enough: Google answers a wrong or too small
        selection with an error banner and a fresh grid. Each round re-reads the
        challenge, because the target and the grid size can both change.
        """
        for round_no in range(MAX_ROUNDS):
            ch = await self._read_challenge(root)
            print(
                f"🎯 reCAPTCHA v2 round {round_no + 1}/{MAX_ROUNDS}: "
                f"target={ch['target']!r} grid={ch['grid']} dynamic={ch['dynamic']}"
            )

            if ch["dynamic"]:
                await self._clear_dynamic_grid(root, ch)
            else:
                for idx in await self._pick(root, ch):
                    await self._click_tile(root, idx)

            await root.locator(VERIFY_BUTTON).click(timeout=CLICK_TIMEOUT_MS)
            outcome = await self._wait_round_outcome(page, root, timeout=10, before=ch)

            if outcome == "token":
                token = await self._read_token(page)
                print(
                    f"✅ reCAPTCHA v2: token after round {round_no + 1} "
                    f"({len(token)} chars)"
                )
                return token
            if outcome == "timeout":
                raise RuntimeError("reCAPTCHA v2: no outcome after verify")
            print(f"🔁 reCAPTCHA v2: round {round_no + 1} rejected, trying again")

        raise RuntimeError("reCAPTCHA v2: challenge not solved in 5 rounds")

    async def _wait_round_outcome(self, page, root, timeout=10, before=None) -> str:
        """What verify produced: "token", "retry" or "timeout".

        "retry" covers both ways Google asks again — an error banner, and a
        silently replaced challenge. `before` is the challenge as read at the
        start of the round; without it a replacement right after the click would
        sit out the whole timeout looking like a challenge nobody answered.
        """
        deadline = time.monotonic() + timeout

        while True:
            if await self._read_token(page):
                return "token"
            for selector in CHALLENGE_ERRORS:
                if await self._visible(root, selector):
                    return "retry"
            if before is not None and await self._read_challenge(root) != before:
                return "retry"
            if time.monotonic() >= deadline:
                return "timeout"
            await asyncio.sleep(TOKEN_POLL_INTERVAL)

    async def _read_challenge(self, root) -> dict:
        """What the grid on screen asks for right now.

        The target is the emphasized word of the instruction; a layout without
        <strong> leaves the whole instruction as the target, because guessing it
        out of a fixed word list is what made unknown challenges unsolvable.
        """
        instruction = await self._text(root, CHALLENGE_DESC)
        target = await self._text(root, CHALLENGE_STRONG) or instruction
        tiles = await root.locator(TILE_WRAPPER).count()
        return {
            "target": target,
            "instruction": instruction,
            "grid": "4x4" if tiles == 16 else "3x3",
            "dynamic": DYNAMIC_MARKER in instruction.lower(),
        }

    async def _text(self, root, selector: str) -> str:
        """Whitespace-normalized text of the first match; "" when there is none."""
        locator = root.locator(selector).first
        if not await locator.count():
            return ""
        return " ".join(((await locator.text_content()) or "").split())

    async def _visible(self, root, selector: str) -> bool:
        try:
            return await root.locator(selector).first.is_visible()
        except Exception:
            return False

    async def _grab_tile_shots(self, root) -> list[bytes]:
        """One screenshot per tile, cropped to that tile.

        The wrapper, not its `img`: reCAPTCHA serves the whole grid as a single
        sprite (378x378 for 3x3) shifted inside a 126x126 window, so an `img`
        screenshot hands every tile to the classifier as the complete grid.
        """
        shots = []
        for tile in await root.locator(TILE_WRAPPER).all():
            shot = await tile.screenshot()
            shots.append(shot)
        return shots

    async def _pick(self, root, ch) -> list[int]:
        """Tile indices to click: the vision LLM first, YOLO on the crops if it fails."""
        tiles = await root.locator(TILE_WRAPPER).count()
        try:
            shot = await root.locator(CHALLENGE_TARGET).screenshot()
            picked = await self.vision_classifier.classify_tiles(
                shot, f"Select all {ch['target']}", ch["grid"]
            )
        except Exception as exc:
            # No API key, a dead endpoint or a missing target element all land
            # here; the per-tile crops still allow the local classifier to try.
            print(
                f"⚠️ reCAPTCHA v2: vision LLM unavailable ({type(exc).__name__}), "
                f"falling back to YOLO"
            )
            picked = await self._pick_with_yolo(root, ch)
        # A hallucinated index would raise deep inside Playwright's nth()
        return [idx for idx in picked if 0 <= idx < tiles]

    async def _pick_with_yolo(self, root, ch) -> list[int]:
        """Local fallback: classify each cropped tile on its own."""
        # `_classify_image_hybrid` speaks underscore names, the page does not
        target = ch["target"].lower().replace(" ", "_")
        picked = []
        for idx, shot in enumerate(await self._grab_tile_shots(root)):
            if await self._classify_image_hybrid(shot, target):
                picked.append(idx)
        return picked

    async def _clear_dynamic_grid(self, root, ch) -> None:
        """Click a refilling grid until it has nothing left to select.

        "Click verify once there are none left": every clicked tile comes back
        as a new one, so passes repeat until the classifier stops finding
        matches — bounded, because a classifier that keeps guessing would
        otherwise click forever.
        """
        for _ in range(MAX_DYNAMIC_PASSES):
            picked = await self._pick(root, ch)
            if not picked:
                return
            for idx in picked:
                await self._click_tile(root, idx)
            # Google swaps the clicked tiles server-side; clicking the next
            # batch before the swap lands selects tiles that are already gone.
            await asyncio.sleep(random.uniform(1.5, 2.0))

    async def _click_tile(self, root, idx: int) -> None:
        await root.locator(TILE_WRAPPER).nth(idx).click(timeout=CLICK_TIMEOUT_MS)
        await asyncio.sleep(random.uniform(0.3, 0.7))

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
