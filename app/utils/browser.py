"""Playwright browser wrapper with stealth capabilities"""
import asyncio
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from app.config import settings
from typing import Optional
try:
    from playwright_stealth import Stealth
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    Stealth = None


# Fictitious https origin for reading the browser's own client hints:
# navigator.userAgentData exists only in a secure context. page.route answers
# it, so nothing leaves the browser (.invalid never resolves anyway).
_HINTS_PROBE_URL = 'https://client-hints.invalid/'
_HINTS_PROBE_JS = """async () => {
  const d = navigator.userAgentData;
  if (!d) return null;
  return await d.getHighEntropyValues(['architecture', 'bitness', 'fullVersionList',
    'model', 'platformVersion', 'uaFullVersion', 'wow64']);
}"""


@dataclass(frozen=True)
class BrowserIdentity:
    """What every page presents: the HTTP User-Agent, navigator.userAgent and
    the client hints (Sec-CH-UA*, navigator.userAgentData) all come from it."""
    user_agent: str
    metadata: dict


def _languages(locale: str) -> tuple:
    """navigator.languages for a locale: the locale and, for a regional one,
    its base language ("en-US" -> ("en-US", "en")). Chromium turns the same
    list into Accept-Language "en-US,en;q=0.9"."""
    base = locale.split('-', 1)[0]
    return (locale, base) if base.lower() != locale.lower() else (locale,)


def _accept_language(languages: tuple) -> str:
    """Accept-Language of desktop Chrome for that list: "en-US,en;q=0.9"."""
    return ','.join([languages[0]] + [f'{lang};q={0.9 - 0.1 * i:.1f}'
                                      for i, lang in enumerate(languages[1:])])


def _unheadless_brands(brands) -> list:
    return [
        {'brand': 'Google Chrome' if b['brand'] == 'HeadlessChrome' else b['brand'],
         'version': b['version']}
        for b in brands
    ]


def _build_identity(user_agent: str, hints: Optional[dict]) -> BrowserIdentity:
    """Headless Chromium says HeadlessChrome in the UA and in its brand list.
    Keep everything else it reports (version, the greased brand Chromium
    generated for this version, platform) and only swap that word, the same
    substitution playwright-stealth does on the JS side."""
    if not hints or not hints.get('brands') or not hints.get('fullVersionList'):
        raise RuntimeError('Browser reported no client hints')
    user_agent = user_agent.replace('HeadlessChrome/', 'Chrome/')
    metadata = {
        'brands': _unheadless_brands(hints['brands']),
        'fullVersionList': _unheadless_brands(hints['fullVersionList']),
        'fullVersion': hints.get('uaFullVersion', ''),
        'platform': hints.get('platform', ''),
        'platformVersion': hints.get('platformVersion', ''),
        'architecture': hints.get('architecture', ''),
        'model': hints.get('model', ''),
        'mobile': bool(hints.get('mobile', False)),
        'bitness': hints.get('bitness', ''),
        'wow64': bool(hints.get('wow64', False)),
    }
    if 'Headless' in user_agent or 'Headless' in repr(metadata):
        raise RuntimeError('Browser identity still says Headless')
    return BrowserIdentity(user_agent=user_agent, metadata=metadata)


class BrowserManager:
    """Manage Playwright browser instances with stealth configuration"""
    
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._proxy_contexts = {}
        self._context_cleanup = set()
        # (browser, task reading its identity): one probe per launched browser
        self._identity = None
        # applies the identity to popups (window.open) of our pages
        self._popup_tasks = set()
        self._languages = _languages(settings.browser_locale)
        # stealth's navigator.languages patch must say what Accept-Language says
        self._stealth = Stealth(navigator_platform_override="Linux x86_64", webgl_vendor_override="Google Inc. (Intel)", webgl_renderer_override="ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)", navigator_languages_override=self._languages) if HAS_STEALTH else None
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

        Every page gets its own context (closed together with the page by
        close_page) and the browser identity: the HTTP User-Agent, the client
        hints and navigator.userAgent/userAgentData all say Chrome, never
        HeadlessChrome, and Accept-Language matches navigator.languages
        (settings.browser_locale), whatever ``stealth`` is. Popups the page
        opens get the same identity, see _follow_popups.

        Args:
            stealth: Whether to apply stealth patches (default: True)
            proxy: Optional proxy in a dedicated, page-owned context

        Returns:
            Configured page
        """
        browser = await self.get_browser()
        identity = await self._browser_identity(browser)
        if proxy is not None:
            creation = asyncio.create_task(
                browser.new_context(proxy=proxy, **self._context_options(identity)))
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
            # Browser.new_page makes a context owned by the page: page.close()
            # closes it, so cookies never leak between tasks.
            page = await browser.new_page(**self._context_options(identity))

        try:
            self._follow_popups(page.context, identity)
            await self._apply_identity(page, identity)
            if stealth and HAS_STEALTH and self._stealth:
                await self._stealth.apply_stealth_async(page)
        except (Exception, asyncio.CancelledError):
            await self.close_page(page)
            raise

        return page

    def _context_options(self, identity: BrowserIdentity) -> dict:
        """Context-level part of the identity. Playwright applies it to a page
        of the context before the page runs; a popup's first load can still
        go out without the extra header, see _follow_popups."""
        return {
            'user_agent': identity.user_agent,
            'locale': self._languages[0],
            'extra_http_headers': {'Accept-Language': _accept_language(self._languages)},
        }

    async def _apply_identity(self, page: Page, identity: BrowserIdentity) -> None:
        """Override UA, client hints and Accept-Language of this page over CDP.

        The context's user_agent alone is not enough: Playwright then sends
        client-hint metadata without brands, and Chromium fills in its own list,
        so Sec-CH-UA and navigator.userAgentData still say HeadlessChrome. With
        the brands given here both the headers and navigator.userAgentData
        report the same list. acceptLanguage makes navigator.languages the
        full list ("en-US", "en"); the context's locale alone yields only
        "en-US", and requests the renderer starts itself (images, fetch) keep
        that value, hence the Accept-Language extra header of the context
        (_context_options). The CDP session must stay attached: Chromium drops a
        session's overrides when it detaches; it ends with the page.
        Same-process frames inherit it: all iframes, cross-site ones too, since
        site isolation is off (no separate iframe targets exist, checked with
        Target.getTargets), and dedicated workers.
        """
        session = await page.context.new_cdp_session(page)
        await session.send('Emulation.setUserAgentOverride', {
            'userAgent': identity.user_agent,
            'userAgentMetadata': identity.metadata,
            'acceptLanguage': ','.join(self._languages),
        })

    def _follow_popups(self, context: BrowserContext, identity: BrowserIdentity) -> None:
        """Give every later page of this context (window.open popups, links
        with target=_blank) the identity of new_page.

        Playwright reports such a page only after Chromium has resumed it, so
        the override lands while its first load is already running. Measured
        with a local echo server: the popup's document, its subresources and
        an early fetch went out with the right User-Agent, but with Chromium's
        own client hints (Sec-CH-UA brand "HeadlessChrome") and Accept-Language
        "en-US" (the bare locale, without ",en;q=0.9"); not even the context's
        extra headers reach that first navigation. Requests after the hook and
        navigator.* of the popup match the opener. Rewriting the early headers
        would take context-wide request routing (every request of every page
        through the driver, HTTP cache off), so it is not done. Stealth scripts
        are per page and do not reach popups either.
        """
        def on_page(page: Page) -> None:
            task = asyncio.ensure_future(self._apply_popup_identity(page, identity))
            self._popup_tasks.add(task)
            task.add_done_callback(self._popup_tasks.discard)

        context.on('page', on_page)

    async def _apply_popup_identity(self, page: Page, identity: BrowserIdentity) -> None:
        try:
            await self._apply_identity(page, identity)
        except Exception as exc:  # popup closed already, or the browser died
            print(f'Popup identity not applied: {type(exc).__name__}', flush=True)

    async def _browser_identity(self, browser: Browser) -> BrowserIdentity:
        """Identity of this browser instance, read once and shared by all pages.

        The probe runs in its own task: a caller cancelled mid-probe must not
        leave a half-created context behind, and concurrent callers share it.
        A failed probe is not cached, the next page retries.
        """
        entry = self._identity
        task = entry[1] if entry is not None and entry[0] is browser else None
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = asyncio.create_task(self._read_identity(browser))
            # Retrieve the outcome even if every waiter was cancelled.
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._identity = (browser, task)
        return await asyncio.shield(task)

    async def _read_identity(self, browser: Browser) -> BrowserIdentity:
        session = await browser.new_browser_cdp_session()
        try:
            version = await session.send('Browser.getVersion')
        finally:
            await session.detach()
        context = await browser.new_context()
        try:
            page = await context.new_page()
            await page.route(_HINTS_PROBE_URL, lambda route: route.fulfill(
                status=200, content_type='text/html', body='<!doctype html><title></title>'))
            await page.goto(_HINTS_PROBE_URL)
            # brands, mobile and platform come with every high-entropy result
            hints = await page.evaluate(_HINTS_PROBE_JS)
        finally:
            await context.close()
        return _build_identity(version['userAgent'], hints)

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
        entry, self._identity = self._identity, None
        if entry is not None and not entry[1].done():
            entry[1].cancel()
            await asyncio.gather(entry[1], return_exceptions=True)
        if self._context_cleanup:
            await asyncio.gather(*tuple(self._context_cleanup))
        if self._popup_tasks:
            await asyncio.gather(*tuple(self._popup_tasks), return_exceptions=True)
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Global browser instance
browser_manager = BrowserManager()
