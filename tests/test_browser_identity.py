"""Browser identity of BrowserManager.new_page in the real Chromium of the image.

An echo HTTP server on 127.0.0.1 inside the test process records the headers
of every request; the page loads it (document, same-origin and cross-origin
iframe, image, fetch) and the headers are compared with navigator.* of the same
page. Loopback only, no network: like the other offline browser tests
(test_slider_browser.py) this runs wherever Playwright's Chromium is installed,
including the CI image test step. The SSRF guard of the solvers is not involved:
new_page() itself never validates URLs.
"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pydantic import ValidationError

from app.config import Settings, settings
from app.utils.browser import BrowserManager, _build_identity, _languages

CLIENT_HINTS = ('sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform')

NAVIGATOR_JS = """async () => {
  const d = navigator.userAgentData;
  return {ua: navigator.userAgent,
          brands: d ? d.brands.map(b => ({brand: b.brand, version: b.version})) : null,
          mobile: d ? d.mobile : null, platform: d ? d.platform : null,
          languages: Array.from(navigator.languages), language: navigator.language};
}"""


class EchoServer:
    """Records request headers per path; serves a page with subresources."""

    def __init__(self):
        self.requests = {}
        records = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                records.setdefault(self.path, []).append(
                    {k.lower(): v for k, v in self.headers.items()})
                port = self.server.server_address[1]
                if self.path == '/':
                    body = ('<!doctype html><body>'
                            '<iframe id="same" src="/frame"></iframe>'
                            f'<iframe id="cross" src="http://localhost:{port}/xframe"></iframe>'
                            '<img src="/img.png">'
                            '<script>window.fetched = fetch("/fetch").then(r => r.text())</script>'
                            '</body>').encode()
                    ctype = 'text/html'
                elif self.path in ('/frame', '/xframe', '/popup'):
                    body, ctype = b'<!doctype html><body>frame</body>', 'text/html'
                else:
                    body, ctype = b'ok', 'text/plain'
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.base = f'http://127.0.0.1:{self._server.server_address[1]}'
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def header_languages(value):
    """Accept-Language "en-US,en;q=0.9" -> ["en-US", "en"] (q-values dropped,
    Chromium lists them in navigator.languages order)."""
    return [part.split(';')[0].strip() for part in value.split(',')]


def sec_ch_ua(brands):
    """Sec-CH-UA as Chromium serialises navigator.userAgentData.brands."""
    return ', '.join(f'"{b["brand"]}";v="{b["version"]}"' for b in brands)


# Proxy branch: the echo hosts bypass the dead proxy, so it is never used, but
# the page still gets its own proxy context (Playwright proxies loopback too).
DEAD_PROXY = {'server': 'http://127.0.0.1:9', 'bypass': '127.0.0.1,localhost'}


@pytest.mark.parametrize('kwargs', [{}, {'stealth': False}, {'proxy': DEAD_PROXY}],
                         ids=['plain', 'no-stealth', 'proxy-context'])
def test_http_headers_match_navigator_without_headless(kwargs):
    async def scenario(echo):
        manager = BrowserManager()
        try:
            page = await manager.new_page(**kwargs)
            browser = await manager.get_browser()
            await page.goto(echo.base + '/')  # waits for the iframes' load too
            await page.evaluate('window.fetched')
            navigator = {'page': await page.evaluate(NAVIGATOR_JS)}
            for frame in page.frames[1:]:
                navigator[frame.url.rsplit('/', 1)[1]] = await frame.evaluate(NAVIGATOR_JS)
            context = page.context
            await manager.close_page(page)
            return browser.version, navigator, context
        finally:
            await manager.close()

    with EchoServer() as echo:
        version, navigator, _ = asyncio.run(scenario(echo))
        requests = dict(echo.requests)

    nav = navigator['page']
    assert set(navigator) == {'page', 'frame', 'xframe'}
    # every frame, cross-origin included, reports the same identity
    assert all(n == nav for n in navigator.values()), navigator
    # derived from the running browser, not a hard-coded Chrome version
    assert f'Chrome/{version.split(".")[0]}.' in nav['ua']
    assert 'Headless' not in nav['ua']
    brands = [b['brand'] for b in nav['brands']]
    assert 'Google Chrome' in brands and 'Chromium' in brands, brands
    assert not any('Headless' in b for b in brands)

    assert set(requests) == {'/', '/frame', '/xframe', '/img.png', '/fetch'}
    for path, seen in requests.items():
        for headers in seen:
            assert headers['user-agent'] == nav['ua'], (path, headers)
            # loopback is a secure context: Chromium sends the default hints
            for name in CLIENT_HINTS:
                assert name in headers, (path, name, headers)
            assert headers['sec-ch-ua'] == sec_ch_ua(nav['brands']), (path, headers)
            assert headers['sec-ch-ua-platform'] == f'"{nav["platform"]}"', (path, headers)
            assert headers['sec-ch-ua-mobile'] == ('?1' if nav['mobile'] else '?0'), (path, headers)
            assert not any('headless' in v.lower() for v in headers.values()), (path, headers)
            # headless Chromium sends no Accept-Language unless told to
            assert 'accept-language' in headers, (path, headers)
            assert header_languages(headers['accept-language']) == nav['languages'], (path, headers)
    # default browser_locale, as desktop Chrome with an en-US UI says it
    assert nav['languages'] == ['en-US', 'en'] and nav['language'] == 'en-US'
    assert requests['/'][0]['accept-language'] == 'en-US,en;q=0.9'


@pytest.mark.parametrize('kwargs', [{}, {'stealth': False}, {'proxy': DEAD_PROXY}],
                         ids=['plain', 'no-stealth', 'proxy-context'])
def test_browser_locale_setting_drives_accept_language_and_navigator(monkeypatch, kwargs):
    monkeypatch.setattr(settings, 'browser_locale', 'de-DE')

    async def scenario(echo):
        manager = BrowserManager()
        try:
            page = await manager.new_page(**kwargs)
            await page.goto(echo.base + '/')
            await page.evaluate('window.fetched')
            nav = await page.evaluate(NAVIGATOR_JS)
            await manager.close_page(page)
            return nav
        finally:
            await manager.close()

    with EchoServer() as echo:
        nav = asyncio.run(scenario(echo))
        requests = dict(echo.requests)

    assert nav['languages'] == ['de-DE', 'de'] and nav['language'] == 'de-DE'
    for path, seen in requests.items():
        for headers in seen:
            assert headers.get('accept-language') == 'de-DE,de;q=0.9', (path, headers)


def test_languages_of_a_locale():
    assert _languages('en-US') == ('en-US', 'en')
    assert _languages('pt-BR') == ('pt-BR', 'pt')
    assert _languages('ru') == ('ru',)


@pytest.mark.parametrize('value', ['', 'en_US', 'en-US,en', 'en-US;q=1', 'e', 'english'])
def test_browser_locale_rejects_what_is_not_a_language_tag(value):
    with pytest.raises(ValidationError):
        Settings(browser_locale=value)


async def _popup_settled(manager):
    """Wait until the popup hook of the manager has finished (bounded)."""
    for _ in range(100):
        if not manager._popup_tasks:
            return
        await asyncio.sleep(0.05)
    raise AssertionError('popup identity hook still running')


@pytest.mark.parametrize('proxy', [None, DEAD_PROXY], ids=['plain', 'proxy-context'])
def test_popup_gets_the_identity_of_its_opener(proxy):
    """Popups bypass new_page(): the context's 'page' hook gives them the same
    UA, client hints and Accept-Language. Requests after the hook carry them;
    the popup's first load can go out before it (see _follow_popups), so only
    the User-Agent and the first Accept-Language entry are checked there."""
    async def scenario(echo):
        manager = BrowserManager()
        try:
            page = await manager.new_page(proxy=proxy)
            await page.goto(echo.base + '/fetch')
            opener = await page.evaluate(NAVIGATOR_JS)
            async with page.expect_popup() as popup_info:
                await page.evaluate(f'window.open("{echo.base}/popup")')
            popup = await popup_info.value
            await popup.wait_for_load_state()
            await _popup_settled(manager)
            await popup.evaluate('fetch("/popup-later").then(r => r.text())')
            in_popup = await popup.evaluate(NAVIGATOR_JS)
            await manager.close_page(page)
            return opener, in_popup
        finally:
            await manager.close()

    with EchoServer() as echo:
        opener, in_popup = asyncio.run(scenario(echo))
        first = echo.requests['/popup'][0]
        later = echo.requests['/popup-later'][0]

    assert first['user-agent'] == opener['ua']
    assert 'Headless' not in first['user-agent']
    assert header_languages(first['accept-language'])[0] == opener['language']
    assert in_popup == opener
    assert later['user-agent'] == in_popup['ua']
    assert later['sec-ch-ua'] == sec_ch_ua(in_popup['brands'])
    assert later['sec-ch-ua-platform'] == f'"{in_popup["platform"]}"'
    assert header_languages(later['accept-language']) == in_popup['languages']
    assert not any('headless' in v.lower() for v in later.values()), later


@pytest.mark.parametrize('proxy', [None, DEAD_PROXY], ids=['plain', 'proxy-context'])
def test_each_page_has_its_own_context_closed_with_it(proxy):
    async def scenario(echo):
        manager = BrowserManager()
        try:
            browser = await manager.get_browser()
            first = await manager.new_page(proxy=proxy)
            second = await manager.new_page(proxy=proxy)
            assert first.context is not second.context
            await first.goto(echo.base + '/fetch')
            await first.evaluate('document.cookie = "task=one; path=/"')
            await second.goto(echo.base + '/fetch')
            leaked = await second.evaluate('document.cookie')
            open_contexts = len(browser.contexts)
            await manager.close_page(first)
            await manager.close_page(second)
            return leaked, open_contexts, len(browser.contexts)
        finally:
            await manager.close()

    with EchoServer() as echo:
        leaked, open_contexts, after_close = asyncio.run(scenario(echo))

    assert leaked == ''
    assert open_contexts == 2   # the identity probe leaves no context behind
    assert after_close == 0


def test_build_identity_swaps_only_headless_brand():
    hints = {'brands': [{'brand': 'Chromium', 'version': '9'},
                        {'brand': 'Not.A/Brand', 'version': '24'},
                        {'brand': 'HeadlessChrome', 'version': '9'}],
             'fullVersionList': [{'brand': 'HeadlessChrome', 'version': '9.0.1.2'}],
             'platform': 'Linux', 'mobile': False, 'architecture': 'x86', 'bitness': '64'}
    identity = _build_identity('Mozilla/5.0 (X11) HeadlessChrome/9.0.1.2 Safari/537.36', hints)
    assert identity.user_agent == 'Mozilla/5.0 (X11) Chrome/9.0.1.2 Safari/537.36'
    assert identity.metadata['brands'] == [
        {'brand': 'Chromium', 'version': '9'}, {'brand': 'Not.A/Brand', 'version': '24'},
        {'brand': 'Google Chrome', 'version': '9'}]
    assert identity.metadata['fullVersionList'] == [{'brand': 'Google Chrome', 'version': '9.0.1.2'}]
    assert identity.metadata['platform'] == 'Linux'


@pytest.mark.parametrize('hints', [None, {}, {'brands': [], 'fullVersionList': []}])
def test_build_identity_without_client_hints_fails(hints):
    with pytest.raises(RuntimeError, match='no client hints'):
        _build_identity('Mozilla/5.0 Chrome/9.0.0.0', hints)
