"""Binance CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class BinanceCaptchaSolver(BaseSolver):
    """
    Binance CAPTCHA solver - crypto exchange protection
    
    Binance uses:
    - Slider puzzles
    - Image selection
    - Behavioral analysis
    - Anti-bot detection
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Binance CAPTCHA"""
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
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """)
                
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Binance CAPTCHA widget
                await page.wait_for_selector('[class*="captcha"], [id*="captcha"]', timeout=10000)
                
                # Check for slider challenge
                slider = await page.query_selector('.captcha-slider, .slider-handle')
                if slider:
                    box = await slider.bounding_box()
                    track = await page.query_selector('.captcha-track, .slider-track')
                    track_box = await track.bounding_box() if track else None
                    
                    if box and track_box:
                        # Human-like drag
                        start_x = box['x'] + box['width'] / 2
                        start_y = box['y'] + box['height'] / 2
                        end_x = track_box['x'] + track_box['width'] - 30
                        
                        await page.mouse.move(start_x, start_y)
                        await page.mouse.down()
                        
                        # Move with curve
                        steps = 40
                        for i in range(steps):
                            progress = (i + 1) / steps
                            x = start_x + (end_x - start_x) * progress
                            y = start_y + 8 * (1 - (2 * progress - 1) ** 2)
                            await page.mouse.move(x, y)
                            await asyncio.sleep(0.012)
                        
                        await page.mouse.up()
                        await asyncio.sleep(2)
                
                # Check for image selection
                images = await page.query_selector_all('.captcha-image, .image-option')
                if images and len(images) > 1:
                    # Use Vision LLM
                    from workers.classifiers.vision_llm import VisionLLMClassifier
                    classifier = VisionLLMClassifier()
                    
                    instruction_elem = await page.query_selector('.captcha-instruction')
                    instruction = await instruction_elem.text_content() if instruction_elem else "Select matching images"
                    
                    screenshot = await page.screenshot()
                    indices = await classifier.classify_tiles(screenshot, instruction, "3x3")
                    
                    for idx in indices:
                        if idx < len(images):
                            box = await images[idx].bounding_box()
                            if box:
                                await page.mouse.click(
                                    box['x'] + box['width'] / 2,
                                    box['y'] + box['height'] / 2
                                )
                                await asyncio.sleep(0.5)
                    
                    # Submit
                    submit = await page.query_selector('.captcha-submit, button[type="submit"]')
                    if submit:
                        await submit.click()
                        await asyncio.sleep(2)
                
                # Wait for token
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            const input = document.querySelector('input[name*="captcha"], input[name*="token"]');
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
