"""Shared input contract and "widget" page for the browser solvers.

A client's page can sit behind a WAF that blocks this worker's IP while the
CAPTCHA provider's own scripts stay reachable — the public demo pages do
exactly that to datacenter ranges. `render_mode="widget"` intercepts the
navigation to `page_url` inside the browser and answers it with a minimal page
carrying the provider script and the site key: the widget is solved in the
origin the provider expects, without loading the client's site.

The navigation is recognised as "the first main-frame navigation of the page",
not by comparing URLs: Chromium canonicalises the URL it requests (default
port dropped, non-ASCII path percent-encoded, `%2e%2e` segments resolved), so a
string comparison with `page_url` silently missed and the client's site loaded.

Site keys reaching `widget_html` have passed SITE_KEY_RE in
`check_browser_input`, so they cannot break out of the attribute or the URL
they are interpolated into.
"""
import re
from typing import Any, Dict, Tuple

SITE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{kind} widget</title></head>
<body>
{container}
<script src="{script}" async defer></script>
</body>
</html>
"""

# task type -> (provider script, widget container), both with a {site_key} slot
_WIDGETS: Dict[str, Tuple[str, str]] = {
    "yandex_smartcaptcha": (
        "https://smartcaptcha.yandexcloud.net/captcha.js",
        '<div class="smart-captcha" data-sitekey="{site_key}"></div>',
    ),
    "turnstile": (
        "https://challenges.cloudflare.com/turnstile/v0/api.js",
        '<div class="cf-turnstile" data-sitekey="{site_key}"></div>',
    ),
    "hcaptcha": (
        "https://js.hcaptcha.com/1/api.js",
        '<div class="h-captcha" data-sitekey="{site_key}"></div>',
    ),
    "recaptcha_v3": (
        "https://www.google.com/recaptcha/api.js?render={site_key}",
        '<div class="g-recaptcha" data-sitekey="{site_key}" data-size="invisible"></div>',
    ),
    # used by RecaptchaV2Solver in render_mode="widget"
    "recaptcha_v2": (
        "https://www.google.com/recaptcha/api.js",
        '<div class="g-recaptcha" data-sitekey="{site_key}"></div>',
    ),
}


def check_browser_input(input_data: Dict[str, Any]) -> Tuple[str, str, str]:
    """Validate what every browser solver needs.

    Returns (site_key, page_url, render_mode); raises ValueError on a missing or
    malformed field, before the SSRF guard and before a browser is started.
    """
    site_key = input_data.get("site_key")
    page_url = input_data.get("page_url")
    render_mode = input_data.get("render_mode")

    if not site_key or not isinstance(site_key, str):
        raise ValueError("Missing site_key")
    if not page_url or not isinstance(page_url, str):
        raise ValueError("Missing page_url")
    # fullmatch: with match() the `$` also accepts a trailing "\n"
    if not SITE_KEY_RE.fullmatch(site_key):
        raise ValueError(
            "site_key must be 1-100 characters from [A-Za-z0-9_-]"
        )
    # optional field: only an absent key or null means "page"; a falsy value of
    # another type (false, 0, []) is a client error, not the default
    if render_mode is None:
        render_mode = "page"
    elif not isinstance(render_mode, str):
        raise ValueError(f"render_mode must be a string, got {type(render_mode).__name__}")
    if render_mode not in ("page", "widget"):
        raise ValueError(f"render_mode must be 'page' or 'widget', got {render_mode!r}")
    return site_key, page_url, render_mode


def widget_html(kind: str, site_key: str) -> str:
    """Minimal page rendering `kind`'s widget for `site_key` (already validated)."""
    try:
        script, container = _WIDGETS[kind]
    except KeyError:
        raise ValueError(f"unknown widget kind: {kind!r}") from None
    return _PAGE.format(
        kind=kind,
        container=container.format(site_key=site_key),
        script=script.format(site_key=site_key),
    )


def _any_url(url: str) -> bool:
    return True


async def install_widget_page(page, page_url: str, kind: str, site_key: str) -> None:
    """Answer the page's first main-frame navigation with the widget page.

    Call right before `page.goto(page_url)`: that navigation is the first one
    on a fresh page, so it is the one served, whatever form Chromium gives its
    URL. Every other request — the provider's scripts and frames, sub-frame
    navigations — falls through to the network or to routes installed earlier.
    Once the widget page is served the handler removes itself, so the rest of
    the traffic does not pass through Python.
    """
    body = widget_html(kind, site_key)
    served = False

    async def serve_first_navigation(route) -> None:
        nonlocal served
        request = route.request
        if not served and request.is_navigation_request() and request.frame == page.main_frame:
            served = True
            await route.fulfill(status=200, content_type="text/html", body=body)
            await page.unroute(_any_url, serve_first_navigation)
            return
        await route.fallback()

    # a predicate, not a string: Playwright reads a string as a glob
    await page.route(_any_url, serve_first_navigation)
