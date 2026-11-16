"""Slider CAPTCHA solver with human-like drag movement."""
import asyncio
import math
import random
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit
from playwright.async_api import Page, Locator

from .base import BaseSolver
from app.utils.browser import browser_manager
from workers.solvers.url_guard import validate_page_url

GOTO_TIMEOUT_MS = 30000
# After the drag the handle must stay invisible this long to count as a pass:
# a widget may hide the handle while it verifies and show it again on a reject.
SETTLE_MS = 3000
SETTLE_POLL_MS = 500

# Alibaba nc (AWSC nc 1.97.0 and the older sd/ncpc nc.js on g.alicdn.com) keeps
# the handle VISIBLE after a pass: the same span#nc_1_n1z only changes class
# btn_slide -> btn_ok and the text becomes "验证通过". A reject or block
# replaces the whole slider with div.errloading ("验证失败，点击框体重试"), which
# removes the handle. Both checked in the widget source and live (demo appkey
# with TEST_PASS / TEST_BLOCK).
NC_PASSED = '.nc_scale .btn_ok'
NC_FAILED = '.nc-container .errloading'


class SliderCaptchaSolver(BaseSolver):
    """
    Solves slider CAPTCHA by dragging the handle with human-like movement.
    
    Supports common slider CAPTCHA patterns:
    - Alibaba/AliExpress slider (nc_1_n1z, nc_iconfont, btn_slide)
    - Generic slider with role="slider"
    - Custom sliders with .slider-track or .nc_scale
    """
    
    # DOM markers for slider detection
    SLIDER_HANDLES = ['#nc_1_n1z', '.nc_iconfont.btn_slide', '[role="slider"]', '.slider-handle']
    SLIDER_TRACKS = ['#nc_1__scale_text', '.nc_scale', '.slider-track', '.slider-rail']
    
    async def detect(self, page: Page, selectors: Optional[List[str]] = None) -> bool:
        """Detect if slider CAPTCHA is present on the page (default selectors
        unless the caller passes the ones the task uses)."""
        for selector in selectors or (self.SLIDER_HANDLES + self.SLIDER_TRACKS):
            if await page.locator(selector).count() > 0:
                return True
        return False
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve slider CAPTCHA by dragging the handle.
        
        Args:
            input_data: {
                "page_url": "https://example.com",
                "handle_selector": "#custom-handle",  # optional, str or list of str
                "track_selector": "#custom-track"      # optional, str or list of str
            }
        
        Returns:
            {"success": True, "cookies": [...], "url": str, "user_agent": str}:
            cookies of the final page's host (see _page_cookies), the final
            page.url and the browser's navigator.userAgent, so the client can
            continue the session the worker unlocked. Any failure raises, so
            the task ends as failed.
        """
        page_url = input_data.get('page_url')
        if not page_url:
            raise ValueError('page_url is required')
        
        # Allow custom selectors from input_data
        handle_selectors = _selectors(input_data.get('handle_selector'), self.SLIDER_HANDLES, 'handle_selector')
        track_selectors = _selectors(input_data.get('track_selector'), self.SLIDER_TRACKS, 'track_selector')
        
        # SSRF guard before the browser is touched (shared by all URL solvers)
        page_url = await asyncio.to_thread(validate_page_url, page_url)
        
        page = await browser_manager.new_page()
        
        try:
            await page.goto(page_url, timeout=GOTO_TIMEOUT_MS, wait_until='domcontentloaded')
            # Read before the drag: a page that navigates on a pass would
            # destroy the execution context, and the value does not change.
            user_agent = await page.evaluate('navigator.userAgent')
            await page.wait_for_timeout(1000)
            
            for attempt in range(3):
                try:
                    await self._drag_slider(page, handle_selectors, track_selectors)
                    
                    # Success = no VISIBLE handle left, or the nc pass marker;
                    # an nc failure box is never a success (see NC_PASSED).
                    # Tracks are not checked: Alibaba nc keeps its track
                    # (.nc_scale, #nc_1__scale_text) after a pass. Same handle
                    # selectors as the drag: custom ones are invisible to the
                    # defaults.
                    if await self._stays_passed(page, handle_selectors):
                        return await self._result(page, user_agent)
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        raise RuntimeError(f'Slider solve failed: {e}') from e
                    await page.wait_for_timeout(500)
            
            raise RuntimeError('Slider still present after 3 attempts')
        finally:
            await page.close()
    
    async def _drag_slider(self, page: Page, handle_selectors: List[str] = None, track_selectors: List[str] = None) -> None:
        """Drag slider handle with human-like movement."""
        handle_selectors = handle_selectors or self.SLIDER_HANDLES
        track_selectors = track_selectors or self.SLIDER_TRACKS
        
        handle = await self._locate(page, handle_selectors)
        track = await self._locate(page, track_selectors)
        
        knob_box = await handle.bounding_box()
        rail_box = await track.bounding_box()
        
        if not knob_box or not rail_box:
            raise LookupError('Slider bounds unavailable')
        
        start_x = knob_box['x'] + knob_box['width'] / 2
        start_y = knob_box['y'] + knob_box['height'] / 2
        distance = rail_box['x'] + rail_box['width'] - knob_box['width'] / 2 - start_x
        
        if distance <= 0:
            raise LookupError('Slider travel unavailable')
        
        # Move to start position
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        
        try:
            # Human-like drag with curve, easing and jitter
            steps = random.randint(35, 55)
            curve = random.uniform(7, 15)
            
            for step in range(1, steps + 1):
                progress = step / steps
                # Easing function (cosine ease-in-out)
                eased = (1 - math.cos(math.pi * progress)) / 2
                
                # X position with jitter
                x = start_x + distance * eased + random.uniform(-0.7, 0.7)
                
                # Y position with curve (arc) and jitter
                y = start_y + curve * math.sin(math.pi * progress) + random.uniform(-1.2, 1.2)
                
                await page.mouse.move(x, y)
                
                # Random delay between steps
                await page.wait_for_timeout(random.randint(12, 32))
        finally:
            await page.mouse.up()
        
        # Wait for verification
        await page.wait_for_timeout(1500)
    
    async def _locate(self, page: Page, selectors: List[str]) -> Locator:
        """First VISIBLE element over the selector list, in selector order.

        A selector may match several elements ([role="slider"], a hidden
        template copy before the live widget): each match is checked with
        is_visible(), and a single element (nth) avoids the strict-mode error
        bounding_box() raises on a multi-element locator.
        """
        for selector in selectors:
            locator = page.locator(selector)
            for i in range(await locator.count()):
                element = locator.nth(i)
                if await element.is_visible():
                    return element
        raise LookupError(f'No visible element found for selectors: {selectors}')

    async def _visible_handle(self, page: Page, selectors: List[str]) -> bool:
        """True while any handle selector still matches a visible element."""
        try:
            await self._locate(page, selectors)
        except LookupError:
            return False
        return True

    async def _passed(self, page: Page, selectors: List[str]) -> bool:
        """One look at the page: nc says passed, or no handle is visible and
        nc does not show its failure box."""
        if await self._visible(page, NC_PASSED):
            return True
        if await self._visible(page, NC_FAILED):
            return False
        return not await self._visible_handle(page, selectors)

    async def _visible(self, page: Page, selector: str) -> bool:
        """True if any element matching selector is visible."""
        locator = page.locator(selector)
        for i in range(await locator.count()):
            if await locator.nth(i).is_visible():
                return True
        return False

    async def _stays_passed(self, page: Page, selectors: List[str]) -> bool:
        """Passed now and at every poll for SETTLE_MS."""
        for waited in range(0, SETTLE_MS + 1, SETTLE_POLL_MS):
            if waited:
                await page.wait_for_timeout(SETTLE_POLL_MS)
            if not await self._passed(page, selectors):
                return False
        return True

    async def _result(self, page: Page, user_agent: str) -> Dict[str, Any]:
        """Success payload: what the client needs to reuse the unlocked session.
        page.url and context cookies need no JS context, so a page that is
        navigating after the pass does not turn success into a retry."""
        url = page.url
        return {
            'success': True,
            'cookies': _page_cookies(await page.context.cookies(), url),
            'url': url,
            'user_agent': user_agent,
        }


def _page_cookies(cookies: List[Dict[str, Any]], page_url: str) -> List[Dict[str, Any]]:
    """Cookies of the page's host only: the host itself, its subdomains and the
    parent-domain cookies the browser would send to the page (Domain=example.com
    set by www.example.com; Playwright reports such a cookie with a leading dot).
    A host-only cookie of a parent HOST (`example.com` without the dot) is not
    sent to www.example.com and is dropped. Chromium never stores a cookie for
    a public suffix, so a parent domain here is a real site. Cookies of other
    sites in the context (third-party frames, redirects passed on the way) are
    dropped."""
    host = (urlsplit(page_url).hostname or '').lower()
    if not host:
        return []
    kept = []
    for cookie in cookies:
        raw = (cookie.get('domain') or '').lower()
        domain = raw.lstrip('.')
        if not domain:
            continue
        parent = raw.startswith('.') and host.endswith('.' + domain)
        if domain == host or parent or domain.endswith('.' + host):
            kept.append(cookie)
    return kept


def _selectors(value: Any, default: List[str], field: str) -> List[str]:
    """Selector override from input_data: None -> default, str -> [str], list of str."""
    if value is None:
        return default
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ValueError(f'{field} must be a non-empty string or list of strings')
    return value
