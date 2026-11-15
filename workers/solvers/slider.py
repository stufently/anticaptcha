"""Slider CAPTCHA solver with human-like drag movement."""
import math
import random
from typing import Optional, List, Dict, Any
from playwright.async_api import Page, Locator

from .base import BaseSolver
from .widget_page import install_widget_page
from app.utils.browser import browser_manager


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
    
    async def detect(self, page: Page) -> bool:
        """Detect if slider CAPTCHA is present on the page."""
        for selector in self.SLIDER_HANDLES + self.SLIDER_TRACKS:
            if await page.locator(selector).count() > 0:
                return True
        return False
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve slider CAPTCHA by dragging the handle.
        
        Args:
            input_data: {
                "page_url": "https://example.com",
                "handle_selector": "#custom-handle",  # optional
                "track_selector": "#custom-track"      # optional
            }
        
        Returns:
            dict with 'success' (bool) and optional 'error' (str)
        """
        page_url = input_data.get('page_url')
        if not page_url:
            return {'success': False, 'error': 'page_url is required'}
        
        # Allow custom selectors from input_data
        handle_selectors = input_data.get('handle_selector', self.SLIDER_HANDLES)
        track_selectors = input_data.get('track_selector', self.SLIDER_TRACKS)
        
        # Convert single selector to list
        if isinstance(handle_selectors, str):
            handle_selectors = [handle_selectors]
        if isinstance(track_selectors, str):
            track_selectors = [track_selectors]
        
        # Create browser context
        page = await browser_manager.new_page()
        
        try:
            # Navigate to page
            await page.goto(page_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(1000)
            
            # Install widget page interception if needed
            await install_widget_page(page, 'slider', page_url)
            
            for attempt in range(3):
                try:
                    await self._drag_slider(page, handle_selectors, track_selectors)
                    # Wait for verification
                    await page.wait_for_timeout(1500)
                    
                    # Check if slider is still present
                    if not await self.detect(page):
                        return {'success': True}
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        return {'success': False, 'error': f'Slider solve failed: {str(e)}'}
                    await page.wait_for_timeout(500)
            
            return {'success': False, 'error': 'Slider still present after 3 attempts'}
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
        """Locate first matching element from selector list."""
        for selector in selectors:
            locator = page.locator(selector)
            if await locator.count() > 0:
                return locator
        raise LookupError(f'No element found for selectors: {selectors}')
