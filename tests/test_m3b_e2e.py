"""M3b end-to-end: reCAPTCHA v2 against Google's own published test key.

Skipped unless ANTICAPTCHA_E2E=1 — it launches a real Chromium and talks to
Google. The solver is driven exactly like the worker does (class from the
SOLVERS registry, setup/solve/cleanup). `page_url` is https://example.com/ and
`render_mode` is "widget", so the navigation is answered with our own page
carrying the v2 widget and only Google's scripts go over the network.

The test key passes without an image challenge, so this covers the entry path —
widget page, checkbox click, token poll. The rounds are covered by
tests/test_m3b_unit.py against a fake bframe DOM: solving a real challenge
needs a vision LLM key, which this image does not have.

The test closes `browser_manager` inside the event loop that used it: the
manager is a module-level singleton, and a transport left behind by a closed
loop makes the next test hang.
"""
import asyncio
import os

import pytest

from app.utils.browser import browser_manager
from workers.task_worker import SOLVERS

pytestmark = pytest.mark.skipif(
    os.environ.get("ANTICAPTCHA_E2E") != "1",
    reason="provider e2e: set ANTICAPTCHA_E2E=1 (needs network)",
)

PAGE_URL = "https://example.com/"
# Google's published test key pair, https://developers.google.com/recaptcha/docs/faq
RECAPTCHA_TEST_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
MIN_TOKEN_LENGTH = 100


async def _run_solver(task_type, input_data):
    """One task, the way the worker runs it, then release the browser."""
    solver = SOLVERS[task_type]()
    try:
        await solver.setup()
        return await solver.solve(input_data)
    finally:
        await solver.cleanup()
        await browser_manager.close()


def test_E7_v2_testkey():
    """The test key issues a token from the checkbox, no image challenge."""
    result = asyncio.run(
        _run_solver(
            "recaptcha_v2",
            {
                "site_key": RECAPTCHA_TEST_KEY,
                "page_url": PAGE_URL,
                "render_mode": "widget",
            },
        )
    )
    token = result["token"]
    assert len(token) >= MIN_TOKEN_LENGTH, f"token is {len(token)} chars"
    # the token is a real Google response, not an echo of the site key
    assert RECAPTCHA_TEST_KEY not in token
