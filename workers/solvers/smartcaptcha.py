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
POLL_INTERVAL = 0.2
_deadline = contextvars.ContextVar('smartcaptcha_deadline', default=None)
CHECKBOX_FRAME = 'iframe[data-testid="checkbox-iframe"]'


async def _bounded(operation):
    """Bound every browser roundtrip, including locator and mouse operations."""
    deadline = _deadline.get()
    remaining = DEADLINE_SECONDS if deadline is None else deadline - time.monotonic()
    return await asyncio.wait_for(operation, max(0.5, remaining))


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
        deadline = time.monotonic() + DEADLINE_SECONDS
        marker = _deadline.set(deadline)
        dragged = clicked = executed = False
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
                        if not executed:
                            executed = await _bounded(page.evaluate("""() => {
                                if (window.smartCaptcha && typeof window.smartCaptcha.execute === 'function') {
                                    window.smartCaptcha.execute();
                                    return true;
                                }
                                return false;
                            }"""))
                        await asyncio.sleep(POLL_INTERVAL)
                        continue
                    frame = page.frame_locator(CHECKBOX_FRAME).first
                    thumb = frame.locator('.SliderCaptcha [data-testid="thumb"]').first
                    if not dragged and await _bounded(thumb.is_visible()):
                        await _bounded(thumb.scroll_into_view_if_needed())
                        start = await _bounded(thumb.bounding_box())
                        track = await _bounded(frame.locator('.SliderCaptcha').first.bounding_box())
                        if start and track:
                            x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
                            await _bounded(page.mouse.move(x, y))
                            await _bounded(page.mouse.down())
                            try:
                                await _bounded(page.mouse.move(track['x'] + track['width'] - 1, y, steps=15))
                            finally:
                                await _bounded(page.mouse.up())
                            dragged = True
                    button = frame.locator('#js-button').first
                    if not clicked and await _bounded(button.is_visible()):
                        await _bounded(button.click())
                        clicked = True
                except (asyncio.TimeoutError, PlaywrightError):
                    # A loading/replaced frame can race a lookup; a stalled
                    # renderer consumes the remaining deadline and ends here.
                    pass
                await asyncio.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        finally:
            _deadline.reset(marker)
        raise RuntimeError('SmartCaptcha: no token within 60s')

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
