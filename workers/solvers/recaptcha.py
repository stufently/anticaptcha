"""reCAPTCHA v2/v3 solvers with stealth capabilities"""
import asyncio
import random
import re
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
TILE_SWAP_TIMEOUT = 5        # seconds to wait for clicked dynamic tiles to refill
CALL_TIMEOUT = 5             # bound on one page call made outside a poll
MIN_CALL_TIMEOUT = 0.5       # least time a page call gets, even past a deadline

# (picture URL, selected) of every tile wrapper. Google marks a selected tile
# on its <td>; the wrapper itself is checked too.
TILE_STATES_JS = """els => els.map(w => {
    const img = w.querySelector('img');
    const cell = w.closest('td');
    const cls = 'rc-imageselect-tileselected';
    return [img ? img.getAttribute('src') : null,
            w.classList.contains(cls) || !!(cell && cell.classList.contains(cls))];
})"""

# Local fallback classes are singular underscore names ("fire_hydrant").
LOCAL_ARTICLES = {"a", "an", "the"}
LOCAL_SINGULARS = {"bus": "bus", "buses": "bus", "stairs": "stairs", "taxis": "taxi"}
LOCAL_PHRASES = {"mountains or hills": "mountain", "mountain or hill": "mountain"}


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
            token = await self._read_token(page, deadline)
            if token:
                return token
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(TOKEN_POLL_INTERVAL)

    async def _read_token(self, page, deadline: Optional[float] = None) -> Optional[str]:
        """One token read off the page; None when there is no token yet.

        Bounded: a page whose JavaScript hangs would otherwise keep a poll
        that promises 6 or 10 seconds waiting forever.
        """
        try:
            return await self._bounded(page.evaluate(TOKEN_JS), deadline) or None
        except Exception:
            return None

    @staticmethod
    def _budget(deadline: Optional[float]) -> float:
        """Seconds one page call may take: what is left of `deadline`, never
        less than MIN_CALL_TIMEOUT, and CALL_TIMEOUT outside a poll."""
        if deadline is None:
            return CALL_TIMEOUT
        return max(deadline - time.monotonic(), MIN_CALL_TIMEOUT)

    async def _bounded(self, awaitable, deadline: Optional[float] = None):
        return await asyncio.wait_for(awaitable, self._budget(deadline))

    @staticmethod
    def _stalled(deadline: float, started: float) -> bool:
        """The deadline has passed and this poll pass spent time on a call
        that did not answer, so the rest of the pass is not worth waiting for.
        A fast pass still runs to the end, so timeout=0 means one full look."""
        now = time.monotonic()
        return now >= deadline and now - started >= MIN_CALL_TIMEOUT

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
                await self._click_tiles(root, await self._pick(root, ch))

            # The screen as verify finds it: a dynamic grid has swapped tiles
            # since `ch`, and a banner left over from the previous round must
            # not pass for the answer to this one.
            before = await self._read_challenge(root)
            banners = await self._visible_banners(root)
            await root.locator(VERIFY_BUTTON).click(timeout=CLICK_TIMEOUT_MS)
            outcome = await self._wait_round_outcome(
                page, root, timeout=10, before=before, banners=banners
            )

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

    async def _wait_round_outcome(
        self, page, root, timeout=10, before=None, banners=()
    ) -> str:
        """What verify produced: "token", "retry" or "timeout".

        "retry" covers both ways Google asks again — an error banner, and a
        silently replaced challenge (new instruction, grid size or pictures).
        `before` is the challenge as it stood when verify was clicked; without
        it a replacement would sit out the whole timeout looking like a
        challenge nobody answered. `banners` were already visible then: such a
        banner speaks for the previous round and counts only once it has gone
        and come back.
        """
        deadline = time.monotonic() + timeout
        stale = set(banners)

        while True:
            started = time.monotonic()
            if await self._read_token(page, deadline):
                return "token"
            for selector in CHALLENGE_ERRORS:
                if self._stalled(deadline, started):
                    return "timeout"
                visible = await self._visible(root, selector, deadline)
                if visible and selector not in stale:
                    return "retry"
                if visible is False:
                    stale.discard(selector)
            if before is not None and not self._stalled(deadline, started):
                try:
                    now = await self._bounded(self._read_challenge(root, deadline), deadline)
                except Exception:
                    now = None  # a read that did not answer is no news
                if now is not None and now != before:
                    return "retry"
            if time.monotonic() >= deadline:
                return "timeout"
            await asyncio.sleep(TOKEN_POLL_INTERVAL)

    async def _read_challenge(self, root, deadline: Optional[float] = None) -> dict:
        """What the grid on screen asks for right now.

        The target is the emphasized word of the instruction; a layout without
        <strong> leaves the whole instruction as the target, because guessing it
        out of a fixed word list is what made unknown challenges unsolvable.
        `images` are the tile picture URLs: Google may replace the pictures
        and keep everything else.
        """
        instruction = await self._text(root, CHALLENGE_DESC, deadline)
        target = await self._text(root, CHALLENGE_STRONG, deadline) or instruction
        tiles = await self._bounded(root.locator(TILE_WRAPPER).count(), deadline)
        images = tuple(src for src, _ in await self._tile_states(root, deadline))
        return {
            "images": images,
            "target": target,
            "instruction": instruction,
            "grid": "4x4" if tiles == 16 else "3x3",
            "dynamic": DYNAMIC_MARKER in instruction.lower(),
        }

    async def _text(self, root, selector: str, deadline: Optional[float] = None) -> str:
        """Whitespace-normalized text of the first match; "" when there is none."""
        locator = root.locator(selector).first
        if not await self._bounded(locator.count(), deadline):
            return ""
        text = await self._bounded(locator.text_content(), deadline)
        return " ".join((text or "").split())

    async def _visible(self, root, selector: str, deadline: Optional[float] = None):
        """True/False, or None when the page did not answer in time."""
        try:
            return await self._bounded(root.locator(selector).first.is_visible(), deadline)
        except Exception:
            return None

    async def _visible_banners(self, root) -> frozenset:
        return frozenset(
            [selector for selector in CHALLENGE_ERRORS if await self._visible(root, selector)]
        )

    async def _tile_states(self, root, deadline: Optional[float] = None) -> list:
        """(picture URL, selected) of every tile, in tile order."""
        states = await self._bounded(
            root.locator(TILE_WRAPPER).evaluate_all(TILE_STATES_JS), deadline
        )
        return [(src, bool(selected)) for src, selected in states]

    async def _tile_srcs(self, root) -> list:
        """Tile picture URLs; [] when the grid could not be read."""
        try:
            return [src for src, _ in await self._tile_states(root)]
        except Exception:
            return []

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
            # an index named twice would be clicked twice, which unselects it
            picked = list(dict.fromkeys(await self.vision_classifier.classify_tiles(
                shot, f"Select all {ch['target']}", ch["grid"]
            )))
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
        # `_classify_image_hybrid` speaks singular underscore names, the page
        # says "fire hydrants"
        target = self._local_class(ch["target"])
        picked = []
        for idx, shot in enumerate(await self._grab_tile_shots(root)):
            if await self._classify_image_hybrid(shot, target):
                picked.append(idx)
        return picked

    @staticmethod
    def _local_class(target: str) -> str:
        """The page's wording as a local class name: "fire hydrants" ->
        "fire_hydrant", "a bus" -> "bus", "Select all images with traffic
        lights" -> "traffic_light"."""
        text = re.sub(r"^\s*select all (images|squares) with\s+", "", target.lower())
        words = re.sub(r"[^a-z ]+", " ", text.split(".")[0]).split()
        while words and words[0] in LOCAL_ARTICLES:
            words.pop(0)
        phrase = " ".join(words)
        if phrase in LOCAL_PHRASES:
            return LOCAL_PHRASES[phrase]
        if words:
            words[-1] = RecaptchaV2Solver._singular(words[-1])
        return "_".join(words)

    @staticmethod
    def _singular(word: str) -> str:
        if word in LOCAL_SINGULARS:
            return LOCAL_SINGULARS[word]
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"
        if word.endswith(("ches", "shes", "xes", "sses")):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word

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
            before = await self._tile_srcs(root)
            clicked = await self._click_tiles(root, picked)
            if not clicked:
                print("⚠️ reCAPTCHA v2: every picked tile is already selected, verifying")
                return
            # Google swaps the clicked tiles server-side; classifying before
            # the swap lands sees the old pictures and clicks them again.
            if not await self._wait_tiles_swapped(root, clicked, before):
                print(
                    f"⚠️ reCAPTCHA v2: tiles {clicked} not replaced within "
                    f"{TILE_SWAP_TIMEOUT}s, picking again anyway"
                )
        print(
            f"⚠️ reCAPTCHA v2: dynamic grid still has matches after "
            f"{MAX_DYNAMIC_PASSES} passes, verifying anyway"
        )

    async def _wait_tiles_swapped(self, root, clicked: list, before: list) -> bool:
        """Wait up to TILE_SWAP_TIMEOUT for every clicked tile to show a new picture."""
        if not before:
            # the grid could not be read: the old fixed pause is all there is
            await asyncio.sleep(random.uniform(1.5, 2.0))
            return False
        deadline = time.monotonic() + TILE_SWAP_TIMEOUT
        while True:
            try:
                now = [src for src, _ in await self._tile_states(root, deadline)]
            except Exception:
                now = before
            if all(
                idx < len(now) and idx < len(before) and now[idx] != before[idx]
                for idx in clicked
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(TOKEN_POLL_INTERVAL)

    async def _click_tiles(self, root, picked: list) -> list[int]:
        """Click the picked tiles that are not selected yet; return those clicked.

        A second click on a selected tile unselects it.
        """
        if not picked:
            return []
        try:
            selected = {i for i, (_, sel) in enumerate(await self._tile_states(root)) if sel}
        except Exception:
            selected = set()
        clicked = []
        for idx in picked:
            if idx in selected:
                print(f"↪️ reCAPTCHA v2: tile {idx} already selected, not clicking it again")
                continue
            await self._click_tile(root, idx)
            clicked.append(idx)
        return clicked

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
    # Each grecaptcha probe is bounded: by the time left in a wait (at least
    # MIN_EVAL_TIMEOUT), or by PROBE_TIMEOUT for a single check. Hung page
    # JavaScript must not hold the worker past the waits above.
    MIN_EVAL_TIMEOUT = 0.5
    PROBE_TIMEOUT = 2

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

    async def _has_execute(self, page, deadline: Optional[float] = None) -> bool:
        """True when grecaptcha.execute can be called on this page right now;
        False when it cannot or the page does not answer in time."""
        if deadline is None:
            timeout = self.PROBE_TIMEOUT
        else:
            timeout = max(self.MIN_EVAL_TIMEOUT, deadline - time.monotonic())
        try:
            return bool(await asyncio.wait_for(page.evaluate(self.EXECUTE_PRESENT_JS), timeout))
        except Exception:
            return False

    async def _wait_for_execute(self, page, timeout: float) -> bool:
        """Poll for grecaptcha.execute for up to `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            if await self._has_execute(page, deadline):
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
