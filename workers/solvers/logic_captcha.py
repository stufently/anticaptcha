"""Logic CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class LogicCaptchaSolver(BaseSolver):
    """
    Logic CAPTCHA solver - pattern recognition and logical puzzles
    
    Logic CAPTCHA uses:
    - Pattern recognition (find the odd one out)
    - Sequence completion
    - Visual puzzles
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Logic CAPTCHA"""
        page_url = input_data.get('page_url')
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            from workers.classifiers.vision_llm import VisionLLMClassifier
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for logic puzzle
                await page.wait_for_selector('.logic-captcha, .puzzle-captcha', timeout=10000)
                
                # Get instruction
                instruction_elem = await page.query_selector('.captcha-instruction, .puzzle-text')
                instruction = await instruction_elem.text_content() if instruction_elem else "Solve the puzzle"
                
                # Get puzzle images
                images = await page.query_selector_all('.puzzle-image, .captcha-image')
                
                if not images:
                    return {'success': False, 'error': 'Puzzle images not found'}
                
                # Take screenshot
                screenshot = await page.screenshot()
                
                # Use Vision LLM to solve
                classifier = VisionLLMClassifier()
                
                # Determine puzzle type and solve
                if 'odd one out' in instruction.lower() or 'different' in instruction.lower():
                    # Find odd one out
                    result = await classifier.classify_image(
                        screenshot,
                        f"{instruction}. Return the index (0-{len(images)-1}) of the different image."
                    )
                    
                    try:
                        idx = int(result.strip())
                        if 0 <= idx < len(images):
                            box = await images[idx].bounding_box()
                            if box:
                                await page.mouse.click(
                                    box['x'] + box['width'] / 2,
                                    box['y'] + box['height'] / 2
                                )
                                await asyncio.sleep(1)
                    except:
                        pass
                
                elif 'sequence' in instruction.lower() or 'next' in instruction.lower():
                    # Complete sequence
                    result = await classifier.classify_image(
                        screenshot,
                        f"{instruction}. Return the index (0-{len(images)-1}) of the correct next image."
                    )
                    
                    try:
                        idx = int(result.strip())
                        if 0 <= idx < len(images):
                            box = await images[idx].bounding_box()
                            if box:
                                await page.mouse.click(
                                    box['x'] + box['width'] / 2,
                                    box['y'] + box['height'] / 2
                                )
                                await asyncio.sleep(1)
                    except:
                        pass
                
                else:
                    # Generic puzzle - click all matching
                    result = await classifier.classify_tiles(
                        screenshot,
                        instruction,
                        f"{len(images)}x1"
                    )
                    
                    for idx in result:
                        if idx < len(images):
                            box = await images[idx].bounding_box()
                            if box:
                                await page.mouse.click(
                                    box['x'] + box['width'] / 2,
                                    box['y'] + box['height'] / 2
                                )
                                await asyncio.sleep(0.5)
                
                # Submit
                submit = await page.query_selector('button[type="submit"], .captcha-submit')
                if submit:
                    await submit.click()
                    await asyncio.sleep(2)
                
                # Check for token
                token = await page.evaluate('''() => {
                    const input = document.querySelector('input[name*="captcha"]');
                    return input ? input.value : null;
                }''')
                
                await page.close()
                
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': 'Token not received'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
