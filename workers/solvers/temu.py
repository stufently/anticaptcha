"""Temu CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class TemuCaptchaSolver(BaseSolver):
    """
    Temu CAPTCHA solver - marketplace protection
    
    Temu uses:
    - Slider puzzles
    - Image verification
    - Click challenges
    - Behavioral analysis
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Temu CAPTCHA"""
        page_url = input_data.get('page_url')
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                # Use stealth mode
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = await context.new_page()
                
                # Add stealth scripts
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)
                
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Temu CAPTCHA widget
                await page.wait_for_selector('[class*="captcha"], [class*="verify"]', timeout=10000)
                
                # Check for slider challenge
                slider = await page.query_selector('.verify-slider, .captcha-slider')
                if slider:
                    box = await slider.bounding_box()
                    track = await page.query_selector('.verify-track, .slider-track')
                    track_box = await track.bounding_box() if track else None
                    
                    if box and track_box:
                        # Human-like drag
                        start_x = box['x'] + box['width'] / 2
                        start_y = box['y'] + box['height'] / 2
                        end_x = track_box['x'] + track_box['width'] - 25
                        
                        await page.mouse.move(start_x, start_y)
                        await page.mouse.down()
                        
                        # Move with curve
                        steps = 38
                        for i in range(steps):
                            progress = (i + 1) / steps
                            x = start_x + (end_x - start_x) * progress
                            y = start_y + 6 * (1 - (2 * progress - 1) ** 2)
                            await page.mouse.move(x, y)
                            await asyncio.sleep(0.015)
                        
                        await page.mouse.up()
                        await asyncio.sleep(2)
                
                # Check for click challenge
                click_targets = await page.query_selector_all('.verify-target, .click-target')
                if click_targets:
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
                            const input = document.querySelector('input[name*="captcha"], input[name*="verify"]');
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
                await context.close()
                
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': 'Token not received'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
