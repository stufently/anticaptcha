"""hCaptcha solver"""
import asyncio
import time
from typing import Any, Dict, Optional

from workers.solvers.url_guard import validate_page_url
from workers.solvers.widget_page import check_browser_input, install_widget_page

# Optional: Playwright for browser automation
try:
    from app.utils.captcha_solver import BaseSolver
    from app.utils.browser import browser_manager
    from app.config import settings
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    # Fallback base class for testing
    class BaseSolver:
        pass


# The checkbox lives in its own iframe. A broader `hcaptcha` match also catches
# the challenge frame, and clicking through two matched frames is a strict-mode
# violation, so the selector pins the checkbox frame by its URL parameter.
CHECKBOX_FRAME = 'iframe[src*="frame=checkbox"]'

TOKEN_JS = """() => {
    const input = document.querySelector('input[name="h-captcha-response"]');
    if (input && input.value) return input.value;
    if (window.hcaptcha && typeof window.hcaptcha.getResponse === 'function') {
        try { return window.hcaptcha.getResponse() || null; } catch (e) { return null; }
    }
    return null;
}"""

CHECKBOX_ELEMENT = "#checkbox"
FRAME_TIMEOUT_MS = 20000
CLICK_TIMEOUT_MS = 10000
POLL_INTERVAL = 0.5
DEADLINE_SECONDS = 20


class HcaptchaSolver(BaseSolver):
    """Solve hCaptcha through its checkbox.

    The image challenge is not solved here: an interactive challenge needs a
    classifier (milestone M3b territory for reCAPTCHA v2), so a task that does
    not get a token from the checkbox flow fails with a RuntimeError saying so.
    """

    def __init__(self):
        super().__init__()
        self.vision_classifier = None

    async def setup(self):
        """Initialize solver"""
        pass

    async def cleanup(self):
        """Cleanup resources"""
        pass

    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve hCaptcha

        Args:
            input_data: {
                "site_key": "...",
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
                # hCaptcha demo answers 403 to datacenters) while the provider's
                # scripts are reachable: serve the widget ourselves.
                await install_widget_page(page, page_url, "hcaptcha", site_key)

            await page.goto(page_url, timeout=60000)

            await page.wait_for_selector(CHECKBOX_FRAME, timeout=FRAME_TIMEOUT_MS)
            await page.frame_locator(CHECKBOX_FRAME).locator(CHECKBOX_ELEMENT).click(
                timeout=CLICK_TIMEOUT_MS
            )
            print("🖱️ hCaptcha: checkbox clicked, polling for the token")

            token = await self._poll_token(page)
            if not token:
                raise RuntimeError(
                    "hCaptcha token not received within 20s (interactive challenge is not supported)"
                )

            return {"token": token}

        finally:
            await page.close()

    async def _poll_token(self, page) -> Optional[str]:
        """Poll the token until DEADLINE_SECONDS; None when it never arrives."""
        deadline = time.monotonic() + DEADLINE_SECONDS

        while True:
            token = await self._read_token(page)
            if token:
                return token
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(POLL_INTERVAL)

    async def _read_token(self, page) -> Optional[str]:
        """One token poll; None when the page is not ready or has no token yet."""
        try:
            return await page.evaluate(TOKEN_JS) or None
        except Exception:
            return None
