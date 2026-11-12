"""Playwright browser wrapper with stealth capabilities"""
import asyncio

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
        self._proxy_contexts = {}
        self._context_cleanup = set()
        self._stealth = Stealth(navigator_platform_override="Linux x86_64", webgl_vendor_override="Google Inc. (Intel)", webgl_renderer_override="ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)") if HAS_STEALTH else None
        self._lock = asyncio.Lock()

    async def get_browser(self) -> Browser:
        """Get or create browser instance"""
        async with self._lock:
            if self._browser is not None and not self._browser.is_connected():
                # A crashed Chromium used to stay in the cache forever: every URL
                # task then failed until the pod was restarted. Drop it (and the
                # context that belonged to it) and launch a fresh one.
                self._browser = None
                self._context = None

            if not self._browser:
                # Reuse the running driver: a second async_playwright().start() per
                # relaunch would leak a node process every time.
                if self._playwright is None:
                    self._playwright = await async_playwright().start()

                # Why --no-sandbox stays: Chromium 158 (playwright 1.65) cannot be
                # sandboxed in this deployment. The default docker seccomp profile
                # blocks the unprivileged user namespaces the sandbox needs
                # ("FATAL ... No usable sandbox!"), the SUID chrome_sandbox helper
                # dies without root ("Zygote process exited prematurely with exit
                # code 82", "not running as root" under no-new-privileges), and the
                # --no-zygote below is rejected outright while the sandbox is on
                # ("Zygote cannot be disabled if sandbox is enabled"). Only
                # seccomp=unconfined / CAP_SYS_ADMIN would change that, and the
                # chart grants neither. Playwright adds --no-sandbox itself while
                # chromium_sandbox=False (its default), so the flag here only
                # restates what runs. A renderer exploit on a client page therefore
                # executes as uid 1000 in the worker: the mitigation is keeping
                # Chromium current, see docs/specs/limits.md ("Browser sandbox").
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

                try:
                    browser = await self._playwright.chromium.launch(
                        headless=settings.headless,
                        args=args
                    )
                except Exception:
                    # A failed launch can leave the driver unusable, so drop it:
                    # the next call starts a new one instead of failing forever.
                    await self._stop_driver()
                    raise

                def on_disconnected(source: Browser) -> None:
                    # Forget only the browser that actually died: a late event from
                    # an old instance must not drop a healthy replacement.
                    if self._browser is source:
                        self._browser = None
                        self._context = None

                browser.on("disconnected", on_disconnected)
                self._browser = browser

            return self._browser

    async def _stop_driver(self) -> None:
        """Best-effort Playwright driver shutdown; never raises."""
        driver, self._playwright = self._playwright, None
        if driver is None:
            return
        try:
            await driver.stop()
        except Exception as exc:
            print(
                f"⚠️ Playwright driver stop failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
    
    async def new_page(self, stealth: bool = True, proxy: Optional[dict] = None) -> Page:
        """
        Create a new page with optional stealth configuration
        
        Args:
            stealth: Whether to apply stealth patches (default: True)
            proxy: Optional proxy in a dedicated, page-owned context
            
        Returns:
            Configured page
        """
        browser = await self.get_browser()
        if proxy is not None:
            creation = asyncio.create_task(browser.new_context(proxy=proxy))
            try:
                context = await asyncio.shield(creation)
            except asyncio.CancelledError:
                # Chromium may already be creating the context. Keep the request
                # alive and dispose of its result without delaying cancellation.
                cleanup = asyncio.create_task(self._close_when_created(creation))
                self._context_cleanup.add(cleanup)
                cleanup.add_done_callback(self._context_cleanup.discard)
                raise
            try:
                page = await context.new_page()
            except (Exception, asyncio.CancelledError):
                await context.close()
                raise
            self._proxy_contexts[id(page)] = context
        else:
            page = await browser.new_page()
        
        try:
            if stealth and HAS_STEALTH and self._stealth:
                await self._stealth.apply_stealth_async(page)
        except (Exception, asyncio.CancelledError):
            await self.close_page(page)
            raise
        
        return page

    async def _close_when_created(self, creation):
        """Own and close a context whose caller was cancelled before receiving it."""
        try:
            context = await creation
            await context.close()
        except Exception as exc:
            # Do not print proxy options or provider error text containing them.
            print(f'Proxy context cleanup ended: {type(exc).__name__}', flush=True)

    async def close_page(self, page):
        """Close the page and only the explicit proxy context we own for it."""
        context = self._proxy_contexts.pop(id(page), None)
        try:
            await page.close()
        finally:
            if context is not None:
                await context.close()

    async def close(self):
        """Close browser"""
        if self._context:
            await self._context.close()
            self._context = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        self._proxy_contexts.clear()
        if self._context_cleanup:
            await asyncio.gather(*tuple(self._context_cleanup))
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Global browser instance
browser_manager = BrowserManager()
