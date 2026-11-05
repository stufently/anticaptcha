"""reCAPTCHA v2/v3 solvers"""
import asyncio
from typing import Dict, Any
from app.utils.captcha_solver import BaseSolver
from app.utils.browser import browser_manager
from app.config import settings
import json


class RecaptchaV2Solver(BaseSolver):
    """Solve reCAPTCHA v2"""
    
    def __init__(self):
        super().__init__()
        self.browser = None
    
    async def setup(self):
        """Setup solver"""
        # Browser will be initialized on first use
        pass
    
    async def cleanup(self):
        """Cleanup resources"""
        pass
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v2
        
        Args:
            input_data: {
                "site_key": "6Le...",
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
            
            # Wait for reCAPTCHA iframe
            await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=10000)
            
            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[src*="recaptcha"][title*="reCAPTCHA"]')
            await checkbox_frame.locator('#recaptcha-anchor').click()
            
            # Wait a bit for challenge to appear
            await asyncio.sleep(1)
            
            # Check if we got a challenge
            challenge_frame = page.frame_locator('iframe[src*="bframe"]')
            
            # Try to get token (might be already solved if site is whitelisted)
            token = await self._extract_token(page)
            
            if not token:
                # We have an image challenge
                # TODO: Implement image classification with Yolo
                # For now, return placeholder
                raise NotImplementedError(
                    "Image challenge solving requires ML models. "
                    "Please ensure Yolo model is trained and available."
                )
            
            return {"token": token}
        
        finally:
            await page.close()
    
    async def _extract_token(self, page) -> str:
        """Extract reCAPTCHA token from page"""
        try:
            token = await page.evaluate('''
                () => {
                    return document.querySelector('textarea[name="g-recaptcha-response"]')?.value;
                }
            ''')
            return token
        except:
            return None


class RecaptchaV3Solver(BaseSolver):
    """Solve reCAPTCHA v3 (invisible)"""
    
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
        Solve reCAPTCHA v3
        
        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com",
                "action": "submit"  # optional
            }
        
        Returns:
            {"token": "..."}
        """
        site_key = input_data.get("site_key")
        page_url = input_data.get("page_url")
        action = input_data.get("action", "submit")
        
        if not site_key or not page_url:
            raise ValueError("Missing site_key or page_url")
        
        page = await browser_manager.new_page()
        
        try:
            # Navigate to page
            await page.goto(page_url, timeout=settings.browser_timeout * 1000)
            
            # Execute reCAPTCHA v3
            token = await page.evaluate('''
                async (args) => {
                    return new Promise((resolve) => {
                        grecaptcha.ready(async () => {
                            const token = await grecaptcha.execute(args.site_key, {
                                action: args.action
                            });
                            resolve(token);
                        });
                    });
                }
            ''', {"site_key": site_key, "action": action})
            
            return {"token": token}
        
        finally:
            await page.close()