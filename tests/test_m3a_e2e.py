"""M3a end-to-end tests against the providers' own test keys.

Skipped unless ANTICAPTCHA_E2E=1: they launch a real Chromium and talk to
Cloudflare, hCaptcha and Google. Solvers are driven exactly like the worker does
(class from the SOLVERS registry, setup/solve/cleanup). `page_url` is
https://example.com/ and `render_mode` is "widget", so the navigation is
answered with our own widget page and only the provider's scripts are fetched —
that is also what makes the tests independent of the client page's WAF.

Every test closes `browser_manager` inside the event loop that used it: the
manager is a module-level singleton, and a transport left behind by a closed
loop makes the next test hang.
"""
import asyncio
import os
import time

import pytest

from app.utils.browser import browser_manager
from workers.task_worker import SOLVERS

pytestmark = pytest.mark.skipif(
    os.environ.get("ANTICAPTCHA_E2E") != "1",
    reason="provider e2e: set ANTICAPTCHA_E2E=1 (needs network)",
)

PAGE_URL = "https://example.com/"
# Cloudflare test keys, https://developers.cloudflare.com/turnstile/troubleshooting/testing/
TURNSTILE_PASS_KEY = "1x00000000000000000000AA"
TURNSTILE_FAIL_KEY = "2x00000000000000000000AB"
TURNSTILE_INTERACTIVE_KEY = "3x00000000000000000000FF"
TURNSTILE_DUMMY_TOKEN = "XXXX.DUMMY.TOKEN.XXXX"
# hCaptcha test keys, https://docs.hcaptcha.com/#integration-testing
HCAPTCHA_PASS_KEY = "10000000-ffff-ffff-ffff-000000000001"
HCAPTCHA_PASS_TOKEN = "10000000-aaaa-bbbb-cccc-000000000001"
# Google's published test key; E5 answers api.js with a stub, so it is never
# really used against Google.
RECAPTCHA_TEST_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
FAKE_V3_TOKEN = "FAKE-V3-TOKEN"
# must equal webgl_renderer_override in app/utils/browser.py
WEBGL_RENDERER = "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)"

FAKE_API_JS = """
window.grecaptcha = {
  ready: function (cb) { cb(); },
  execute: function () { return Promise.resolve("%s"); }
};
""" % FAKE_V3_TOKEN

FINGERPRINT_JS = """() => {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
  let renderer = null;
  if (gl) {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  }
  return {platform: navigator.platform, ua: navigator.userAgent, renderer: renderer};
}"""


async def _run_solver(task_type, input_data):
    """One task, the way the worker runs it, then release the browser."""
    solver = SOLVERS[task_type]()
    try:
        await solver.setup()
        return await solver.solve(input_data)
    finally:
        await solver.cleanup()
        await browser_manager.close()


def test_E1_turnstile_pass():
    """Non-interactive key: the token lands in the hidden input, no click."""
    started = time.monotonic()
    result = asyncio.run(
        _run_solver(
            "turnstile",
            {
                "site_key": TURNSTILE_PASS_KEY,
                "page_url": PAGE_URL,
                "render_mode": "widget",
            },
        )
    )
    elapsed = time.monotonic() - started
    assert result == {"token": TURNSTILE_DUMMY_TOKEN}
    assert elapsed < 15, f"a passing key took {elapsed:.1f}s"


def test_E2_turnstile_fail():
    """Always-failing key: bounded wait, then a RuntimeError naming the deadline."""
    started = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(
            _run_solver(
                "turnstile",
                {
                    "site_key": TURNSTILE_FAIL_KEY,
                    "page_url": PAGE_URL,
                    "render_mode": "widget",
                },
            )
        )
    elapsed = time.monotonic() - started
    assert "30s" in str(excinfo.value)
    assert elapsed < 40, f"the 30s deadline took {elapsed:.1f}s"


def test_E3_turnstile_interactive():
    """Interactive key: no token without a real mouse click on the widget."""
    result = asyncio.run(
        _run_solver(
            "turnstile",
            {
                "site_key": TURNSTILE_INTERACTIVE_KEY,
                "page_url": PAGE_URL,
                "render_mode": "widget",
            },
        )
    )
    assert result == {"token": TURNSTILE_DUMMY_TOKEN}


def test_E4_hcaptcha_pass():
    """hCaptcha test key through the checkbox frame; no image challenge."""
    result = asyncio.run(
        _run_solver(
            "hcaptcha",
            {
                "site_key": HCAPTCHA_PASS_KEY,
                "page_url": PAGE_URL,
                "render_mode": "widget",
            },
        )
    )
    assert result == {"token": HCAPTCHA_PASS_TOKEN}


def test_E5_v3_injects_script(monkeypatch):
    """A page without api.js: the solver injects it and executes.

    Google's api.js is answered with a stub, so the test proves the injection
    path without spending a real v3 call; example.com itself loads over the
    network, as it does for a "page" mode task.
    """

    async def fake_api(route):
        await route.fulfill(
            status=200, content_type="application/javascript", body=FAKE_API_JS
        )

    original_new_page = browser_manager.new_page

    async def new_page(*args, **kwargs):
        page = await original_new_page(*args, **kwargs)
        await page.route("https://www.google.com/recaptcha/api.js*", fake_api)
        return page

    monkeypatch.setattr(browser_manager, "new_page", new_page)

    result = asyncio.run(
        _run_solver(
            "recaptcha_v3",
            {
                "site_key": RECAPTCHA_TEST_KEY,
                "page_url": PAGE_URL,
                "render_mode": "page",
            },
        )
    )
    assert result == {"token": FAKE_V3_TOKEN}


def test_E6_fingerprint():
    """Stealth must not contradict itself: Linux UA, Linux platform, our WebGL."""

    async def scenario():
        page = await browser_manager.new_page(stealth=True)
        try:
            # a real document: on about:blank the UA and WebGL patches do not run
            await page.goto(PAGE_URL, timeout=30000)
            return await page.evaluate(FINGERPRINT_JS)
        finally:
            # closing the browser closes its pages
            await browser_manager.close()

    fingerprint = asyncio.run(scenario())

    assert fingerprint["platform"].startswith("Linux"), fingerprint
    assert "Linux" in fingerprint["ua"], fingerprint
    assert "HeadlessChrome" not in fingerprint["ua"], fingerprint
    assert fingerprint["renderer"] == WEBGL_RENDERER, fingerprint
