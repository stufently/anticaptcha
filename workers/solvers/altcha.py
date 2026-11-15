"""Altcha CAPTCHA solver"""
import asyncio
from typing import Dict, Any
from .base import BaseSolver


class AltchaSolver(BaseSolver):
    """
    Altcha CAPTCHA solver - privacy-focused, proof-of-work
    
    Altcha uses:
    - Proof-of-work challenges
    - Privacy-focused design
    - No tracking or fingerprinting
    - Client-side computation
    """
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve Altcha CAPTCHA"""
        page_url = input_data.get('page_url')
        
        if not page_url:
            return {'success': False, 'error': 'Missing page_url'}
        
        try:
            from app.utils.browser import browser_manager
            
            async with browser_manager.get_browser() as browser:
                page = await browser.new_page()
                await page.goto(page_url, wait_until='networkidle')
                
                # Wait for Altcha widget
                await page.wait_for_selector('altcha-widget, [data-altcha]', timeout=10000)
                
                # Altcha uses proof-of-work, which is computed client-side
                # Wait for the widget to complete computation
                await asyncio.sleep(3)
                
                # Check if auto-solved
                token = await page.evaluate('''() => {
                    return new Promise((resolve) => {
                        const checkToken = () => {
                            // Check for Altcha response in various locations
                            const widget = document.querySelector('altcha-widget');
                            if (widget) {
                                const input = widget.querySelector('input[name="altcha-response"]');
                                if (input && input.value) {
                                    resolve(input.value);
                                    return;
                                }
                            }
                            
                            // Check form data
                            const form = document.querySelector('form');
                            if (form) {
                                const input = form.querySelector('input[name*="altcha"]');
                                if (input && input.value) {
                                    resolve(input.value);
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
                
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': 'Token not received'}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
