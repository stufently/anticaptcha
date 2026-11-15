"""Prosopo CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class ProsopoSolver(BaseSolver):
    """
    Prosopo CAPTCHA solver - decentralized, privacy-focused
    
    Prosopo uses:
    - Decentralized verification
    - Image recognition challenges
    - Privacy-preserving design
    - Blockchain-based verification
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Prosopo CAPTCHA"""
        page_url = input_data.get('page_url')
        site_key = input_data.get('site_key')
        
        if not page_url or not site_key:
            return {'success': False, 'error': 'Missing page_url or site_key'}
        
        try:
            from app.utils.browser import browser_manager
            from workers.classifiers.vision_llm import VisionLLMClassifier
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Prosopo widget
                await page.wait_for_selector('[data-prosopo], .prosopo-captcha', timeout=10000)
                
                # Check for image challenge
                images = await page.query_selector_all('.prosopo-image, .captcha-image')
                
                if images and len(images) > 1:
                    # Use Vision LLM to solve image challenge
                    classifier = VisionLLMClassifier()
                    
                    instruction_elem = await page.query_selector('.prosopo-instruction, .captcha-text')
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
                    submit = await page.query_selector('.prosopo-submit, button[type="submit"]')
                    if submit:
                        await submit.click()
                        await asyncio.sleep(2)
                
                # Wait for token
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            const input = document.querySelector('input[name*="prosopo"], input[name*="captcha"]');
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
