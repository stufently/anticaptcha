"""M3a contract tests, no network: limits and branches the e2e tests cannot see.

Each test is named after the mutant it kills (W01...W17 of the independent
mutation run): the e2e tests talk to providers that answer at once, so a
shortened deadline, a late retry or a skipped redaction went unnoticed there.
Time is a virtual clock where a deadline is under test, so nothing waits.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from workers.solvers import hcaptcha, recaptcha, turnstile
from workers.solvers.widget_page import check_browser_input
from workers.task_worker import _redact

PAGE_URL = "https://example.com/"


class Clock:
    """time.monotonic + asyncio.sleep stand-in: sleeping advances the clock."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        assert self.now < 100, "polling failed to terminate"


def fake_clock(monkeypatch, module):
    clock = Clock()
    monkeypatch.setattr(module, "time", clock)
    # the module's reference only: the event loop itself keeps the real asyncio
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(sleep=clock.sleep))
    return clock


# --- site_key length bounds ------------------------------------------------


def test_W01_one_character_key():
    assert check_browser_input({"site_key": "a", "page_url": PAGE_URL}) == ("a", PAGE_URL, "page")


def test_W02_hundred_character_key():
    key = "a" * 100
    assert check_browser_input({"site_key": key, "page_url": PAGE_URL})[0] == key


# --- Turnstile poll ----------------------------------------------------------


def test_W06_click_schedule(monkeypatch):
    clock = fake_clock(monkeypatch, turnstile)
    solver = turnstile.TurnstileSolver()
    solver._read_token = AsyncMock(return_value=None)
    clicks = []

    async def click(page):
        clicks.append(clock.now)
        return True

    solver._click_checkbox = click
    assert asyncio.run(solver._poll_token(object())) is None
    assert clicks == [8.0, 14.0, 20.0]


def test_W07_late_turnstile_token(monkeypatch):
    clock = fake_clock(monkeypatch, turnstile)
    solver = turnstile.TurnstileSolver()

    async def read(page, deadline=None):
        return "late-token" if clock.now >= 25 else None

    solver._read_token = read
    solver._click_checkbox = AsyncMock(return_value=False)
    assert asyncio.run(solver._poll_token(object())) == "late-token"
    assert clock.now == 25


def test_W07_turnstile_gives_up_at_30s(monkeypatch):
    clock = fake_clock(monkeypatch, turnstile)
    solver = turnstile.TurnstileSolver()
    solver._read_token = AsyncMock(return_value=None)
    solver._click_checkbox = AsyncMock(return_value=False)
    assert asyncio.run(solver._poll_token(object())) is None
    assert clock.now == 30


@pytest.mark.parametrize(
    "frames",
    [
        [],
        [SimpleNamespace(url="https://unrelated.example/?q=challenges.cloudflare.com")],
    ],
    ids=["no-frames", "host-in-query"],
)
def test_W08_no_click_without_provider_frame(frames):
    solver = turnstile.TurnstileSolver()
    solver._container_box = AsyncMock(return_value={"x": 10, "y": 20, "width": 300, "height": 65})
    page = SimpleNamespace(frames=frames, mouse=SimpleNamespace(click=AsyncMock()))
    assert asyncio.run(solver._click_checkbox(page)) is False
    page.mouse.click.assert_not_awaited()


# --- hCaptcha ---------------------------------------------------------------


def test_W09_late_hcaptcha_token(monkeypatch):
    clock = fake_clock(monkeypatch, hcaptcha)
    solver = hcaptcha.HcaptchaSolver()

    async def read(page, deadline=None):
        return "late-hcaptcha" if clock.now >= 10 else None

    solver._read_token = read
    assert asyncio.run(solver._poll_token(object())) == "late-hcaptcha"
    assert clock.now == 10


def test_W10_checkbox_click_budget(monkeypatch):
    click = AsyncMock()
    locator = SimpleNamespace(click=click)
    frame = SimpleNamespace(locator=lambda selector: locator)
    page = SimpleNamespace(
        goto=AsyncMock(),
        wait_for_selector=AsyncMock(),
        frame_locator=lambda selector: frame,
        close=AsyncMock(),
    )
    monkeypatch.setattr(hcaptcha.browser_manager, "new_page", AsyncMock(return_value=page))
    monkeypatch.setattr(hcaptcha, "validate_page_url", lambda url: url)
    solver = hcaptcha.HcaptchaSolver()
    solver._poll_token = AsyncMock(return_value="token")
    result = asyncio.run(solver.solve({"site_key": "key", "page_url": PAGE_URL}))
    assert result == {"token": "token"}
    click.assert_awaited_once_with(timeout=10000)
    page.close.assert_awaited_once()


# --- reCAPTCHA v3 -----------------------------------------------------------


def test_W11_wait_for_page_script(monkeypatch):
    # the page's own api.js defines execute after 4 s: no second copy injected
    clock = Clock()
    monkeypatch.setattr(recaptcha, "time", clock)
    monkeypatch.setattr(
        recaptcha,
        "asyncio",
        SimpleNamespace(sleep=clock.sleep, wait_for=asyncio.wait_for, TimeoutError=asyncio.TimeoutError),
    )
    solver = recaptcha.RecaptchaV3Solver()

    async def has_execute(page, deadline=None):
        return clock.now >= 4

    solver._has_execute = has_execute
    solver._inject_api = AsyncMock(return_value=True)
    solver._execute = AsyncMock(return_value="page-token")
    page = SimpleNamespace(goto=AsyncMock())
    token = asyncio.run(solver._token_from(page, PAGE_URL, "key", "submit", "page"))
    assert token == "page-token"
    solver._inject_api.assert_not_awaited()
    assert clock.now == 4


def test_W12_existing_api_not_reinjected():
    solver = recaptcha.RecaptchaV3Solver()
    solver._has_execute = AsyncMock(return_value=True)
    solver._inject_api = AsyncMock(return_value=True)
    solver._execute = AsyncMock(return_value="existing-token")
    page = SimpleNamespace(goto=AsyncMock())
    token = asyncio.run(solver._token_from(page, PAGE_URL, "key", "submit", "page"))
    assert token == "existing-token"
    solver._inject_api.assert_not_awaited()


def test_W13_execute_timeout_bound(monkeypatch):
    solver = recaptcha.RecaptchaV3Solver()
    solver._has_execute = AsyncMock(return_value=True)
    solver._execute = AsyncMock(return_value="unused")
    observed = []

    async def timed_out(coroutine, timeout):
        observed.append(timeout)
        coroutine.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        recaptcha, "asyncio", SimpleNamespace(wait_for=timed_out, TimeoutError=asyncio.TimeoutError)
    )
    page = SimpleNamespace(goto=AsyncMock())
    with pytest.raises(RuntimeError, match="grecaptcha.execute timed out after 20s"):
        asyncio.run(solver._token_from(page, PAGE_URL, "key", "submit", "page"))
    assert observed == [20]


# --- log redaction ----------------------------------------------------------


def test_W16_redact_list():
    source = {"items": ["T" * 40, "short", 42, None]}
    assert _redact(source) == {"items": ["<40 chars>", "short", 42, None]}
    assert source["items"][0] == "T" * 40


def test_W17_redact_nested_dict():
    source = {"nested": {"token": "T" * 40, "short": "ok"}}
    assert _redact(source) == {"nested": {"token": "<40 chars>", "short": "ok"}}
    assert source["nested"]["token"] == "T" * 40
