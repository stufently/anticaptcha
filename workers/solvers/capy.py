"""Capy Puzzle CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class CapyPuzzleSolver(BaseSolver):
    """
    Capy Puzzle CAPTCHA solver - puzzle piece positioning
    
    Capy uses:
    - Drag puzzle piece to correct position
    - Image matching challenges
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Capy Puzzle CAPTCHA"""
        page_url = input_data.get('page_url')
        site_key = input_data.get('site_key')
        
        if not page_url or not site_key:
            return {'success': False, 'error': 'Missing page_url or site_key'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Capy widget
                await page.wait_for_selector('.capy-captcha', timeout=10000)
                
                # Find puzzle piece
                piece = await page.query_selector('.capy-puzzle-piece')
                target = await page.query_selector('.capy-puzzle-target')
                
                if piece and target:
                    piece_box = await piece.bounding_box()
                    target_box = await target.bounding_box()
                    
                    if piece_box and target_box:
                        # Calculate target position
                        start_x = piece_box['x'] + piece_box['width'] / 2
                        start_y = piece_box['y'] + piece_box['height'] / 2
                        end_x = target_box['x'] + target_box['width'] / 2
                        end_y = target_box['y'] + target_box['height'] / 2
                        
                        # Human-like drag
                        await page.mouse.move(start_x, start_y)
                        await page.mouse.down()
                        
                        # Move with slight curve
                        steps = 35
                        for i in range(steps):
                            progress = (i + 1) / steps
                            x = start_x + (end_x - start_x) * progress
                            y = start_y + (end_y - start_y) * progress + 5 * (1 - (2 * progress - 1) ** 2)
                            await page.mouse.move(x, y)
                            await asyncio.sleep(0.015)
                        
                        await page.mouse.up()
                        await asyncio.sleep(1)
                
                # Wait for token
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            const input = document.querySelector('input[name="capy-token"]');
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
