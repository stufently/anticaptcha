"""Cloudflare Turnstile solver"""
import asyncio
from typing import Dict, Any
from app.utils.captcha_solver import BaseSolver
from app.utils.browser import browser_manager
from app.config import settings


class TurnstileSolver(BaseSolver):
    """Solve Cloudflare Turnstile"""
    
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
        Solve Cloudflare Turnstile
        
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
        
        page = await browser_manager.new_page(stealth=True)
        
        try:
            # Navigate to page with extended timeout
            await page.goto(page_url, timeout=90000, wait_until="domcontentloaded")
            
            # Wait for Turnstile widget with extended timeout
            await page.wait_for_selector('iframe[src*="challenges.cloudflare.com"]', timeout=60000)
            
            # Wait for automatic solving (Turnstile often solves automatically)
            await asyncio.sleep(3)
            
            # Try to extract token
            token = await self._extract_token(page)
            
            if not token:
                # Try alternative extraction methods
                token = await self._extract_token_alternative(page)
            
            if not token:
                raise RuntimeError("Failed to extract Turnstile token")
            
            return {"token": token}
        
        finally:
            await page.close()
    
    async def _extract_token(self, page) -> str:
        """Extract Turnstile token from page"""
        try:
            token = await page.evaluate('''
                () => {
                    return document.querySelector('input[name="cf-turnstile-response"]')?.value;
                }
            ''')
            return token
        except:
            return None
    
    async def _extract_token_alternative(self, page) -> str:
        """Alternative method to extract token"""
        try:
            token = await page.evaluate('''
                () => {
                    // Try to find token in turnstile object
                    if (window.turnstile) {
                        return window.turnstile.getResponse();
                    }
                    return null;
                }
            ''')
            return token
        except:
            return None