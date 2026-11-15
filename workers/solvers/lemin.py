"""Lemin CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class LeminSolver(BaseSolver):
    """
    Lemin CAPTCHA solver - slider + click challenges
    
    Lemin uses:
    - Slider puzzles (drag to position)
    - Click challenges (click specific elements)
    - Behavioral analysis
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Lemin CAPTCHA"""
        page_url = input_data.get('page_url')
        api_key = input_data.get('api_key')
        
        if not page_url or not api_key:
            return {'success': False, 'error': 'Missing page_url or api_key'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Lemin widget
                await page.wait_for_selector('[data-lemin-captcha-id]', timeout=10000)
                
                # Check if slider challenge
                slider = await page.query_selector('.lemin-slider-handle')
                if slider:
                    # Solve slider
                    box = await slider.bounding_box()
                    track = await page.query_selector('.lemin-slider-track')
                    track_box = await track.bounding_box()
                    
                    if box and track_box:
                        # Human-like drag
                        start_x = box['x'] + box['width'] / 2
                        start_y = box['y'] + box['height'] / 2
                        end_x = track_box['x'] + track_box['width'] - 20
                        
                        await page.mouse.move(start_x, start_y)
                        await page.mouse.down()
                        
                        # Move with curve
                        steps = 40
                        for i in range(steps):
                            progress = (i + 1) / steps
                            x = start_x + (end_x - start_x) * progress
                            y = start_y + 10 * (1 - (2 * progress - 1) ** 2)  # Parabolic curve
                            await page.mouse.move(x, y)
                            await asyncio.sleep(0.01)
                        
                        await page.mouse.up()
                        await asyncio.sleep(1)
                
                # Check if click challenge
                click_targets = await page.query_selector_all('.lemin-click-target')
                if click_targets:
                    # Click targets in order
                    for target in click_targets:
                        box = await target.bounding_box()
                        if box:
                            await page.mouse.click(
                                box['x'] + box['width'] / 2,
                                box['y'] + box['height'] / 2
                            )
                            await asyncio.sleep(0.5)
                
                # Wait for token
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            const input = document.querySelector('input[name="lemin-token"]');
                            if (input && input.value) {
                                resolve(input.value);
                            } else {
                                setTimeout(checkToken, 100);
                            }
                        };
                        checkToken();
                        setTimeout(() => resolve(null), 20000);
                    });
                }''')
                
                await page.close()
                
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': 'Token not received'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
