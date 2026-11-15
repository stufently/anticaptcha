"""DataDome CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class DataDomeSolver(BaseSolver):
    """
    DataDome CAPTCHA solver - behavioral analysis
    
    DataDome uses:
    - Browser fingerprinting
    - Behavioral analysis
    - Mouse movement tracking
    - Canvas/WebGL fingerprinting
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve DataDome CAPTCHA"""
        page_url = input_data.get('page_url')
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                # Use stealth mode for DataDome
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = await context.new_page()
                
                # Add stealth scripts
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                """)
                
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for DataDome widget
                await page.wait_for_selector('[id*="datadome"]', timeout=10000)
                
                # Simulate human behavior
                # Move mouse randomly
                for _ in range(10):
                    x = 100 + (_ * 50) % 800
                    y = 100 + (_ * 30) % 600
                    await page.mouse.move(x, y)
                    await asyncio.sleep(0.1)
                
                # Click on page
                await page.mouse.click(500, 400)
                await asyncio.sleep(1)
                
                # Check for slider challenge
                slider = await page.query_selector('.datadome-slider')
                if slider:
                    box = await slider.bounding_box()
                    if box:
                        start_x = box['x'] + 10
                        start_y = box['y'] + box['height'] / 2
                        end_x = box['x'] + box['width'] - 20
                        
                        await page.mouse.move(start_x, start_y)
                        await page.mouse.down()
                        
                        steps = 45
                        for i in range(steps):
                            progress = (i + 1) / steps
                            x = start_x + (end_x - start_x) * progress
                            await page.mouse.move(x, start_y)
                            await asyncio.sleep(0.01)
                        
                        await page.mouse.up()
                        await asyncio.sleep(2)
                
                # Wait for token
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            const cookies = document.cookie.split(';');
                            for (let cookie of cookies) {
                                if (cookie.trim().startsWith('datadome=')) {
                                    resolve(cookie.split('=')[1]);
                                    return;
                                }
                            }
                            setTimeout(checkToken, 100);
                        };
                        checkToken();
                        setTimeout(() => resolve(null), 30000);
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
