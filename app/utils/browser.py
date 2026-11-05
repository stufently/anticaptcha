"""Playwright browser wrapper"""
from playwright.async_api import async_playwright, Browser, Page
from app.config import settings
from typing import Optional


class BrowserManager:
    """Manage Playwright browser instances"""
    
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
    
    async def get_browser(self) -> Browser:
        """Get or create browser instance"""
        if not self._browser:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu'
                ]
            )
        return self._browser
    
    async def new_page(self) -> Page:
        """Create a new page"""
        browser = await self.get_browser()
        return await browser.new_page()
    
    async def close(self):
        """Close browser"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Global browser instance
browser_manager = BrowserManager()