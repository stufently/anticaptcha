"""Shared input contract and "widget" page for the browser solvers.

A client's page can sit behind a WAF that blocks this worker's IP while the
CAPTCHA provider's own scripts stay reachable — the public demo pages do
exactly that to datacenter ranges. `render_mode="widget"` intercepts the
navigation to `page_url` inside the browser and answers it with a minimal page
carrying the provider script and the site key: the widget is solved in the
origin the provider expects, without loading the client's site.

Site keys reaching `widget_html` have passed SITE_KEY_RE in
`check_browser_input`, so they cannot break out of the attribute or the URL
they are interpolated into.
"""
import re
from typing import Any, Callable, Dict, Tuple

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
    # template for milestone M3b; RecaptchaV2Solver does not use it yet
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
    render_mode = input_data.get("render_mode") or "page"

    if not site_key or not isinstance(site_key, str):
        raise ValueError("Missing site_key")
    if not page_url or not isinstance(page_url, str):
        raise ValueError("Missing page_url")
    if not SITE_KEY_RE.match(site_key):
        raise ValueError(
            "site_key must be 1-100 characters from [A-Za-z0-9_-]"
        )
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


def widget_route_matcher(page_url: str) -> Callable[[str], bool]:
    """Build the `page.route` predicate for `page_url`.

    A predicate, not a string: Playwright reads a string as a glob, where the
    `.`, `?` and `*` of a real URL widen the match onto pages that are not ours.
    The fragment is dropped because it never reaches the network layer.
    """
    target = page_url.split("#", 1)[0]

    def matches(url: str) -> bool:
        return url == target

    return matches


async def install_widget_page(page, page_url: str, kind: str, site_key: str) -> None:
    """Serve the widget page for `page_url`; every other request goes out as is."""
    body = widget_html(kind, site_key)

    async def fulfill_widget(route) -> None:
        await route.fulfill(status=200, content_type="text/html", body=body)

    await page.route(widget_route_matcher(page_url), fulfill_widget)
