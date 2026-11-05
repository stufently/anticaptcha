"""hCaptcha solver"""
import asyncio
from typing import Dict, Any
from app.utils.captcha_solver import BaseSolver
from app.utils.browser import browser_manager
from app.config import settings


class HcaptchaSolver(BaseSolver):
    """Solve hCaptcha"""
    
    def __init__(self):
        super().__init__()
    
    async def setup(self):
        """Setup solver"""
        pass
    
    async def cleanup(self):
        """Cleanup resources"""
        pass
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve hCaptcha
        
        Args:
            input_data: {
                "site_key": "...",
                "page_url": "https://example.com"
            }
        
        Returns:
            {"token": "..."}
        """
        site_key = input_data.get("site_key")
        page_url = input_data.get("page_url")
        
        if not site_key or not page_url:
            raise ValueError("Missing site_key or page_url")
        
        page = await browser_manager.new_page()
        
        try:
            # Navigate to page
            await page.goto(page_url, timeout=settings.browser_timeout * 1000)
            
            # Wait for hCaptcha iframe
            await page.wait_for_selector('iframe[src*="hcaptcha"]', timeout=10000)
            
            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[src*="hcaptcha"]')
            await checkbox_frame.locator('.checkbox').click()
            
            # Wait for challenge
            await asyncio.sleep(1)
            
            # Try to extract token
            token = await self._extract_token(page)
            
            if not token:
                # Image challenge - needs ML model
                raise NotImplementedError(
                    "hCaptcha image challenge requires ML models. "
                    "Please ensure Yolo model is trained and available."
                )
            
            return {"token": token}
        
        finally:
            await page.close()
    
    async def _extract_token(self, page) -> str:
        """Extract hCaptcha token from page"""
        try:
            token = await page.evaluate('''
                () => {
                    return document.querySelector('input[name="h-captcha-response"]')?.value;
                }
            ''')
            return token
        except:
            return None