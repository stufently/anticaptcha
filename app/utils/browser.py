"""Playwright browser wrapper with stealth capabilities"""
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from app.config import settings
from typing import Optional
try:
    from playwright_stealth import Stealth
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    Stealth = None


class BrowserManager:
    """Manage Playwright browser instances with stealth configuration"""
    
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._stealth = Stealth() if HAS_STEALTH else None
    
    async def get_browser(self) -> Browser:
        """Get or create browser instance"""
        if not self._browser:
            self._playwright = await async_playwright().start()
            
            args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
            ]
            
            # Add stealth args
            if HAS_STEALTH:
                args.extend([
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                ])
            
            self._browser = await self._playwright.chromium.launch(
                headless=settings.headless,
                args=args
            )
        return self._browser
    
    async def new_page(self, stealth: bool = True) -> Page:
        """
        Create a new page with optional stealth configuration
        
        Args:
            stealth: Whether to apply stealth patches (default: True)
            
        Returns:
            Configured page
        """
        browser = await self.get_browser()
        page = await browser.new_page()
        
        if stealth and HAS_STEALTH and self._stealth:
            await self._stealth.apply_stealth_async(page)
        
        return page
    
    async def new_context(self) -> BrowserContext:
        """Create a new browser context"""
        browser = await self.get_browser()
        return await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
    
    async def close(self):
        """Close browser"""
        if self._context:
            await self._context.close()
            self._context = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Global browser instance
browser_manager = BrowserManager()