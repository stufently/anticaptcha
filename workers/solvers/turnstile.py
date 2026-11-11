"""Cloudflare Turnstile solver"""
import asyncio
import contextvars
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from app.utils.browser import browser_manager
from app.utils.captcha_solver import BaseSolver
from workers.solvers.url_guard import validate_page_url
from workers.solvers.widget_page import check_browser_input, install_widget_page

# The widget iframe now lives in a closed shadow root, so no CSS selector can
# reach it: the token is read from the light DOM (hidden input, then the
# turnstile API) and the checkbox is clicked by container coordinates.
TOKEN_JS = """() => {
    const input = document.querySelector('input[name="cf-turnstile-response"]');
    if (input && input.value) return input.value;
    if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
        try { return window.turnstile.getResponse() || null; } catch (e) { return null; }
    }
    return null;
}"""

CONTAINER_JS = """() => {
    let el = document.querySelector('.cf-turnstile');
    if (!el) {
        const input = document.querySelector('input[name="cf-turnstile-response"]');
        el = input ? input.parentElement : null;
    }
    if (!el) return null;
    // a container below the fold gets no click: bring it into the viewport
    // first, instantly (a smooth scroll would still be moving when measured)
    el.scrollIntoView({block: "center", inline: "center", behavior: "instant"});
    const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, width: r.width, height: r.height};
}"""

PROVIDER_FRAME_HOST = "challenges.cloudflare.com"
GOTO_TIMEOUT_MS = 30000
POLL_INTERVAL = 0.5
DEADLINE_SECONDS = 30
# An interactive widget (3x...FF test key) issues a token only after a real
# mouse click; three attempts, one per mark, is the budget for a task.
CLICK_AT_SECONDS = (8.0, 14.0, 20.0)
CLICK_OFFSET_X = 30.0
# Every page.evaluate in the poll loop is bounded by the time left before the
# deadline, but gets at least this much: hung page JavaScript must not hold the
# worker past the deadline, and a call right at it still gets a fair try.
MIN_EVAL_TIMEOUT = 0.5
# Upper bound for one mouse click: a page that stops answering (renderer hung,
# CDP stalled) must not hold the poll loop past its deadline.
CLICK_TIMEOUT = 5.0

# Deadline of the poll in progress, for the evaluate inside the click step
# (the click is called with the page only). Per asyncio task, not per solver.
_poll_deadline: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "turnstile_poll_deadline", default=None
)


def _eval_timeout(deadline: Optional[float]) -> float:
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_SECONDS
    return max(MIN_EVAL_TIMEOUT, deadline - time.monotonic())


def _is_provider_frame(url: Optional[str]) -> bool:
    """The frame is served by Cloudflare's challenge host (parsed, not substring)."""
    try:
        return urlsplit(url or "").hostname == PROVIDER_FRAME_HOST
    except ValueError:
        return False


class TurnstileSolver(BaseSolver):
    """Solve Cloudflare Turnstile"""

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
        Solve Cloudflare Turnstile

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
                # The client's page may be closed to this IP by a WAF while the
                # provider's scripts are reachable: serve the widget ourselves.
                await install_widget_page(page, page_url, "turnstile", site_key)

            await page.goto(page_url, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")

            token = await self._poll_token(page)
            if not token:
                raise RuntimeError("Turnstile token not received within 30s")

            return {"token": token}

        finally:
            await page.close()

    async def _poll_token(self, page) -> Optional[str]:
        """Poll the token until DEADLINE_SECONDS, clicking the widget on schedule."""
        start = time.monotonic()
        deadline = start + DEADLINE_SECONDS
        _poll_deadline.set(deadline)
        next_click = 0

        while True:
            token = await self._read_token(page, deadline)
            if token:
                return token
            now = time.monotonic()
            if now >= deadline:
                return None
            if next_click < len(CLICK_AT_SECONDS) and now - start >= CLICK_AT_SECONDS[next_click]:
                next_click += 1
                await self._click_checkbox(page)
            await asyncio.sleep(POLL_INTERVAL)

    async def _read_token(self, page, deadline: Optional[float] = None) -> Optional[str]:
        """One token poll; None when the page is not ready, has no token yet or
        its JavaScript does not answer before the deadline."""
        try:
            return await asyncio.wait_for(page.evaluate(TOKEN_JS), _eval_timeout(deadline)) or None
        except Exception:
            return None

    async def _click_checkbox(self, page) -> bool:
        """Mouse-click the widget checkbox; report whether the click happened.

        CSS cannot reach the checkbox (closed shadow root), so the click goes to
        the container's coordinates, ~30 px from its left edge and vertically
        centred — that is where Turnstile draws the checkbox. Skipped when no
        frame is served from the provider host yet or the container has no
        layout box.
        """
        if not any(_is_provider_frame(frame.url) for frame in page.frames):
            print("⏳ Turnstile: no provider frame yet, click skipped")
            return False

        box = await self._container_box(page)
        if not box or not box.get("width") or not box.get("height"):
            print("⏳ Turnstile: widget container has no box yet, click skipped")
            return False

        x = box["x"] + min(CLICK_OFFSET_X, box["width"] / 2)
        y = box["y"] + box["height"] / 2
        timeout = min(CLICK_TIMEOUT, _eval_timeout(_poll_deadline.get()))
        try:
            await asyncio.wait_for(page.mouse.click(x, y), timeout)
        except asyncio.TimeoutError:
            print(f"⚠️ Turnstile: checkbox click timed out after {timeout:.1f}s")
            return False
        print(f"🖱️ Turnstile: clicked the widget checkbox at ({x:.0f}, {y:.0f})")
        return True

    async def _container_box(self, page) -> Optional[Dict[str, float]]:
        """Viewport box of the widget container, scrolled into view first; None
        when it is not laid out or the page does not answer before the deadline."""
        try:
            return await asyncio.wait_for(
                page.evaluate(CONTAINER_JS), _eval_timeout(_poll_deadline.get())
            )
        except Exception as exc:
            print(f"⚠️ Turnstile: container lookup failed ({type(exc).__name__})")
            return None
