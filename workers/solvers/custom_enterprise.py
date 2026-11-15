"""Custom Enterprise CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class CustomEnterpriseSolver(BaseSolver):
    """
    Custom Enterprise CAPTCHA solver - configurable for custom solutions
    
    This solver provides a framework for custom enterprise CAPTCHA solutions.
    It can be configured with:
    - Custom selectors
    - Custom solving strategies
    - Custom validation logic
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Custom Enterprise CAPTCHA"""
        page_url = input_data.get('page_url')
        captcha_type = input_data.get('captcha_type', 'generic')
        custom_config = input_data.get('config', {})
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                # Use stealth mode if configured
                if custom_config.get('stealth', True):
                    context = await browser.new_context(
                        user_agent=custom_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
                        viewport=custom_config.get('viewport', {'width': 1920, 'height': 1080})
                    )
                    
                    page = await context.new_page()
                    
                    # Add stealth scripts
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    """)
                else:
                    page = await browser.new_page()
                
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for CAPTCHA widget
                widget_selector = custom_config.get('widget_selector', '[class*="captcha"]')
                await page.wait_for_selector(widget_selector, timeout=10000)
                
                # Solve based on type
                if captcha_type == 'slider':
                    await self._solve_slider(page, custom_config)
                elif captcha_type == 'image':
                    await self._solve_image(page, custom_config)
                elif captcha_type == 'click':
                    await self._solve_click(page, custom_config)
                elif captcha_type == 'text':
                    await self._solve_text(page, custom_config)
                else:
                    # Generic approach
                    await self._solve_generic(page, custom_config)
                
                # Wait for token
                token_selector = custom_config.get('token_selector', 'input[name*="captcha"], input[name*="token"]')
                token = await page.evaluate(f'''() => {{
                    return new Promise((resolve) => {{
                        const checkToken = () => {{
                            const input = document.querySelector('{token_selector}');
                            if (input && input.value) {{
                                resolve(input.value);
                            }} else {{
                                setTimeout(checkToken, 100);
                            }}
                        }};
                        checkToken();
                        setTimeout(() => resolve(null), 20000);
                    }});
                }}''')
                
                await page.close()
                if custom_config.get('stealth', True):
                    await context.close()
                
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': 'Token not received'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _solve_slider(self, page, config):
        """Solve slider CAPTCHA"""
        handle_selector = config.get('handle_selector', '.slider-handle')
        track_selector = config.get('track_selector', '.slider-track')
        
        handle = await page.query_selector(handle_selector)
        track = await page.query_selector(track_selector)
        
        if handle and track:
            box = await handle.bounding_box()
            track_box = await track.bounding_box()
            
            if box and track_box:
                start_x = box['x'] + box['width'] / 2
                start_y = box['y'] + box['height'] / 2
                end_x = track_box['x'] + track_box['width'] - 20
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                
                steps = 40
                for i in range(steps):
                    progress = (i + 1) / steps
                    x = start_x + (end_x - start_x) * progress
                    y = start_y + 10 * (1 - (2 * progress - 1) ** 2)
                    await page.mouse.move(x, y)
                    await asyncio.sleep(0.01)
                
                await page.mouse.up()
                await asyncio.sleep(2)
    
    async def _solve_image(self, page, config):
        """Solve image selection CAPTCHA"""
        from workers.classifiers.vision_llm import VisionLLMClassifier
        
        image_selector = config.get('image_selector', '.captcha-image')
        instruction_selector = config.get('instruction_selector', '.captcha-instruction')
        
        images = await page.query_selector_all(image_selector)
        instruction_elem = await page.query_selector(instruction_selector)
        
        if images and instruction_elem:
            classifier = VisionLLMClassifier()
            instruction = await instruction_elem.text_content()
            
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
            submit_selector = config.get('submit_selector', '.captcha-submit')
            submit = await page.query_selector(submit_selector)
            if submit:
                await submit.click()
                await asyncio.sleep(2)
    
    async def _solve_click(self, page, config):
        """Solve click challenge CAPTCHA"""
        target_selector = config.get('target_selector', '.click-target')
        targets = await page.query_selector_all(target_selector)
        
        for target in targets:
            box = await target.bounding_box()
            if box:
                await page.mouse.click(
                    box['x'] + box['width'] / 2,
                    box['y'] + box['height'] / 2
                )
                await asyncio.sleep(0.5)
    
    async def _solve_text(self, page, config):
        """Solve text CAPTCHA"""
        from workers.classifiers.vision_llm import VisionLLMClassifier
        
        image_selector = config.get('image_selector', '.captcha-image')
        input_selector = config.get('input_selector', 'input[name*="captcha"]')
        
        image = await page.query_selector(image_selector)
        input_field = await page.query_selector(input_selector)
        
        if image and input_field:
            classifier = VisionLLMClassifier()
            screenshot = await image.screenshot()
            
            # Use Vision LLM to read text
            result = await classifier.classify_image(
                screenshot,
                "Read the text from this CAPTCHA image. Return only the text."
            )
            
            await input_field.fill(result.strip())
            
            # Submit
            submit_selector = config.get('submit_selector', 'button[type="submit"]')
            submit = await page.query_selector(submit_selector)
            if submit:
                await submit.click()
                await asyncio.sleep(2)
    
    async def _solve_generic(self, page, config):
        """Generic solving approach"""
        # Try to find and click submit button
        submit_selector = config.get('submit_selector', 'button[type="submit"], .captcha-submit')
        submit = await page.query_selector(submit_selector)
        
        if submit:
            await submit.click()
            await asyncio.sleep(2)
