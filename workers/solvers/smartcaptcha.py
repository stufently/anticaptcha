"""Yandex SmartCaptcha widget mechanics; challenge solving belongs to M4b."""
import asyncio
import contextvars
import time
from typing import Optional

from playwright.async_api import Error as PlaywrightError

from app.utils.browser import browser_manager
from app.utils.captcha_solver import BaseSolver
from workers.solvers.proxy import parse_proxy
from workers.solvers.url_guard import validate_page_url
from workers.solvers.widget_page import check_browser_input, install_widget_page

DEADLINE_SECONDS = 60
MAX_ACTIONS = 4
ACTION_WAIT_SECONDS = 5
INVISIBLE_DELAY_SECONDS = 3
POLL_INTERVAL = 0.2
_deadline = contextvars.ContextVar('smartcaptcha_deadline', default=None)
CHECKBOX_FRAME = 'iframe[data-testid="checkbox-iframe"]'


async def _bounded(operation):
    """Bound every browser roundtrip, including locator and mouse operations."""
    deadline = _deadline.get()
    remaining = DEADLINE_SECONDS if deadline is None else deadline - time.monotonic()
    return await asyncio.wait_for(operation, max(0.5, remaining))


async def _within_action(operation, deadline):
    """All parts of one gesture share a short absolute deadline, with no floor."""
    return await asyncio.wait_for(operation, max(0, deadline - time.monotonic()))


class SmartCaptchaSolver(BaseSolver):
    async def setup(self):
        pass

    async def cleanup(self):
        pass

    async def solve(self, input_data) -> dict:
        site_key, page_url, render_mode = check_browser_input(input_data)
        page_url = await asyncio.to_thread(validate_page_url, page_url)
        proxy = await asyncio.to_thread(parse_proxy, input_data.get('proxy'))
        page = await browser_manager.new_page(stealth=True, proxy=proxy)
        try:
            if render_mode == 'widget':
                await install_widget_page(page, page_url, 'yandex_smartcaptcha', site_key)
            await page.goto(page_url, timeout=30000, wait_until='domcontentloaded')
            token = await self._poll(page)
            print(f'SmartCaptcha: received token ({len(token)} chars)')
            return {'token': token}
        finally:
            await browser_manager.close_page(page)

    async def _poll(self, page) -> str:
        loaded_at = time.monotonic()
        deadline = loaded_at + DEADLINE_SECONDS
        marker = _deadline.set(deadline)
        actions = 0
        next_action_at = loaded_at
        executed = False
        try:
            while time.monotonic() < deadline:
                try:
                    token = await self._read_token(page)
                    if token:
                        return token
                    if time.monotonic() >= deadline:
                        break
                    kind = await self._challenge_kind(page)
                    if kind:
                        await self._solve_challenge(page, kind)
                    if time.monotonic() >= deadline:
                        break
                    has_checkbox = bool(await _bounded(page.locator(CHECKBOX_FRAME).count()))
                    if not has_checkbox:
                        if not executed and time.monotonic() - loaded_at >= INVISIBLE_DELAY_SECONDS:
                            executed = await _bounded(page.evaluate("""() => {
                                if (window.smartCaptcha && typeof window.smartCaptcha.execute === 'function') {
                                    window.smartCaptcha.execute();
                                    return true;
                                }
                                return false;
                            }"""))
                        await asyncio.sleep(POLL_INTERVAL)
                        continue
                    # Keep polling tokens/challenges while the widget processes
                    # the last gesture. Both kinds of gesture share one budget.
                    if actions >= MAX_ACTIONS or time.monotonic() < next_action_at:
                        await asyncio.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
                        continue
                    frame = page.frame_locator(CHECKBOX_FRAME).first
                    thumb = frame.locator('.SliderCaptcha [data-testid="thumb"]').first
                    slider = await _bounded(thumb.is_visible())
                    button = frame.locator('#js-button').first
                    if slider or await _bounded(button.is_visible()):
                        actions += 1
                        action_deadline = min(deadline, time.monotonic() + ACTION_WAIT_SECONDS)
                        try:
                            if slider:
                                await self._drag_slider(page, thumb, frame, action_deadline)
                            else:
                                await _within_action(button.click(), action_deadline)
                        except (asyncio.TimeoutError, PlaywrightError):
                            pass
                        finally:
                            next_action_at = time.monotonic() + ACTION_WAIT_SECONDS
                        # Even a stalled action may have issued a token. Read it
                        # before checking the poll deadline or attempting anything else.
                        token = await self._read_token(page)
                        if token:
                            return token
                except (asyncio.TimeoutError, PlaywrightError):
                    # A loading/replaced frame can race a lookup; a stalled
                    # renderer consumes the remaining deadline and ends here.
                    pass
                await asyncio.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        finally:
            _deadline.reset(marker)
        raise RuntimeError(f'SmartCaptcha: no token within {DEADLINE_SECONDS}s')

    async def _drag_slider(self, page, thumb, frame, deadline):
        await _within_action(thumb.scroll_into_view_if_needed(), deadline)
        start = await _within_action(thumb.bounding_box(), deadline)
        track = await _within_action(frame.locator('.SliderCaptcha').first.bounding_box(), deadline)
        if not start or not track:
            return
        x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
        await _within_action(page.mouse.move(x, y), deadline)
        try:
            await _within_action(page.mouse.down(), deadline)
            await _within_action(page.mouse.move(track['x'] + track['width'] - 1, y, steps=15), deadline)
        finally:
            await _within_action(page.mouse.up(), deadline)

    async def _read_token(self, page) -> Optional[str]:
        return await _bounded(page.evaluate("""() => {
            const input = document.querySelector('input[name="smart-token"]');
            return input && input.value ? input.value : null;
        }"""))

    async def _challenge_kind(self, page) -> Optional[str]:
        selector = 'iframe[data-testid="advanced-iframe"]'
        if not await _bounded(page.locator(selector).first.is_visible()):
            return None
        root = page.frame_locator(selector).first.locator('.AdvancedCaptcha').first
        if not await _bounded(root.count()):
            return None
        classes = (await _bounded(root.get_attribute('class')) or '').split()
        if 'AdvancedCaptcha_image' in classes:
            return 'text'
        if 'AdvancedCaptcha_silhouette' in classes:
            return 'silhouette'
        return 'unknown'

    async def _solve_challenge(self, page, kind):
        raise RuntimeError(f'SmartCaptcha: {kind} challenge is not supported yet')
