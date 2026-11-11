"""M3a unit tests, no network: browser-solver input contract, widget page, log redaction.

Every test name carries U1 (milestone marker).
"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401  registers api_keys table
from app.models.task import Task
from workers import task_worker
from workers.solvers import hcaptcha, recaptcha, turnstile
from workers.solvers.widget_page import (
    check_browser_input,
    install_widget_page,
    widget_html,
)

PAGE_URL = "https://example.com/"
# Provider test keys, see https://developers.cloudflare.com/turnstile/troubleshooting/testing/
# and https://docs.hcaptcha.com/#integration-testing
TURNSTILE_PASS_KEY = "1x00000000000000000000AA"
HCAPTCHA_TEST_KEY = "10000000-ffff-ffff-ffff-000000000001"
RECAPTCHA_TEST_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# --- check_browser_input -------------------------------------------------


@pytest.mark.parametrize(
    "input_data",
    [
        {},
        {"page_url": PAGE_URL},
        {"site_key": TURNSTILE_PASS_KEY},
        {"site_key": "", "page_url": PAGE_URL},
        {"site_key": TURNSTILE_PASS_KEY, "page_url": ""},
        {"site_key": None, "page_url": None},
    ],
    ids=["empty", "no-key", "no-url", "empty-key", "empty-url", "none-both"],
)
def test_U1_check_browser_input_rejects_missing_fields(input_data):
    with pytest.raises(ValueError):
        check_browser_input(input_data)


@pytest.mark.parametrize(
    "site_key",
    [
        'abc"def',  # quote would close the data-sitekey attribute
        "abc<def",  # angle bracket would inject a tag
        "abc def",  # space
        "a" * 101,  # one over the length cap
        "a" * 100 + "\n",  # `$` alone would accept the trailing newline
        "abc\n",
    ],
    ids=["quote", "angle", "space", "too-long", "trailing-newline-100", "trailing-newline"],
)
def test_U1_check_browser_input_rejects_bad_site_key(site_key):
    with pytest.raises(ValueError):
        check_browser_input({"site_key": site_key, "page_url": PAGE_URL})


@pytest.mark.parametrize(
    "site_key",
    [TURNSTILE_PASS_KEY, HCAPTCHA_TEST_KEY, RECAPTCHA_TEST_KEY],
    ids=["turnstile", "hcaptcha", "recaptcha"],
)
@pytest.mark.parametrize("render_mode", ["page", "widget"])
def test_U1_check_browser_input_accepts_provider_keys(site_key, render_mode):
    assert check_browser_input(
        {"site_key": site_key, "page_url": PAGE_URL, "render_mode": render_mode}
    ) == (site_key, PAGE_URL, render_mode)


def test_U1_check_browser_input_defaults_render_mode_to_page():
    assert check_browser_input({"site_key": TURNSTILE_PASS_KEY, "page_url": PAGE_URL}) == (
        TURNSTILE_PASS_KEY,
        PAGE_URL,
        "page",
    )


@pytest.mark.parametrize(
    "render_mode", ["iframe", "PAGE", "embed", "", 5, False, 0, [], {}, True]
)
def test_U1_check_browser_input_rejects_unknown_render_mode(render_mode):
    with pytest.raises(ValueError):
        check_browser_input(
            {"site_key": TURNSTILE_PASS_KEY, "page_url": PAGE_URL, "render_mode": render_mode}
        )


@pytest.mark.parametrize("render_mode", [None])
def test_U1_check_browser_input_treats_absent_render_mode_as_page(render_mode):
    # the field is optional: null is "not provided"; a falsy value of another
    # type (false, 0, [], "") is invalid, see the rejection test above
    assert check_browser_input(
        {"site_key": TURNSTILE_PASS_KEY, "page_url": PAGE_URL, "render_mode": render_mode}
    ) == (TURNSTILE_PASS_KEY, PAGE_URL, "page")


# --- widget_html ---------------------------------------------------------


@pytest.mark.parametrize(
    "kind,script_url",
    [
        ("turnstile", "https://challenges.cloudflare.com/turnstile/v0/api.js"),
        ("hcaptcha", "https://js.hcaptcha.com/1/api.js"),
        ("recaptcha_v3", "https://www.google.com/recaptcha/api.js?render=" + RECAPTCHA_TEST_KEY),
        ("recaptcha_v2", "https://www.google.com/recaptcha/api.js"),
    ],
)
def test_U1_widget_html_carries_key_and_provider_script(kind, script_url):
    html = widget_html(kind, RECAPTCHA_TEST_KEY if kind.startswith("recaptcha") else "KEY-abc_123")
    key = RECAPTCHA_TEST_KEY if kind.startswith("recaptcha") else "KEY-abc_123"
    assert script_url in html
    assert f'data-sitekey="{key}"' in html


def test_U1_widget_html_recaptcha_v2_has_no_render_param():
    html = widget_html("recaptcha_v2", RECAPTCHA_TEST_KEY)
    assert "render=" not in html


@pytest.mark.parametrize("kind", ["funcaptcha", "", "Turnstile"])
def test_U1_widget_html_rejects_unknown_kind(kind):
    with pytest.raises(ValueError):
        widget_html(kind, TURNSTILE_PASS_KEY)


# --- install_widget_page -------------------------------------------------


class _FakeRequest:
    def __init__(self, url, frame, navigation):
        self.url = url
        self.frame = frame
        self._navigation = navigation

    def is_navigation_request(self):
        return self._navigation


class _FakeRoute:
    def __init__(self, url, frame, navigation=True):
        self.request = _FakeRequest(url, frame, navigation)
        self.fulfilled = None
        self.fell_back = False

    async def fulfill(self, **kwargs):
        self.fulfilled = kwargs

    async def fallback(self):
        self.fell_back = True


class _FakePage:
    def __init__(self):
        self.main_frame = object()
        self.routes = []

    async def route(self, url, handler):
        self.routes.append((url, handler))

    async def unroute(self, url, handler):
        self.routes.remove((url, handler))


def _installed(page_url="https://example.com/p?a=1#x"):
    page = _FakePage()
    asyncio.run(install_widget_page(page, page_url, "turnstile", TURNSTILE_PASS_KEY))
    assert len(page.routes) == 1
    matcher, handler = page.routes[0]
    # a string here would be a Playwright glob: its metacharacters widen the match
    assert not isinstance(matcher, str)
    return page, matcher, handler


@pytest.mark.parametrize(
    "requested",
    [
        "https://example.com/p?a=1",
        # what Chromium requests for ":443", a Unicode path and "%2e%2e"
        "https://example.com/",
        "https://example.com/%D0%BF%D1%83%D1%82%D1%8C",
        "https://example.com/widget",
    ],
)
def test_U1_install_widget_page_serves_first_main_frame_navigation(requested):
    page, matcher, handler = _installed()
    # the URL is not compared: Chromium canonicalises it, any form must match
    assert matcher(requested) is True
    route = _FakeRoute(requested, page.main_frame)
    asyncio.run(handler(route))
    assert route.fulfilled["status"] == 200
    assert route.fulfilled["content_type"] == "text/html"
    assert TURNSTILE_PASS_KEY in route.fulfilled["body"]
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in route.fulfilled["body"]
    assert not route.fell_back
    # served once, then the handler is gone: no traffic through Python after it
    assert page.routes == []


def test_U1_install_widget_page_passes_other_requests_through():
    page, _matcher, handler = _installed()
    script = _FakeRoute("https://challenges.cloudflare.com/x.js", page.main_frame, navigation=False)
    child = _FakeRoute("https://challenges.cloudflare.com/frame", object(), navigation=True)
    for route in (script, child):
        asyncio.run(handler(route))
        assert route.fulfilled is None
        assert route.fell_back
    assert len(page.routes) == 1  # still waiting for the main-frame navigation

    first = _FakeRoute("https://example.com/", page.main_frame)
    asyncio.run(handler(first))
    assert first.fulfilled is not None
    # a navigation racing the unroute is not served a second time
    second = _FakeRoute("https://example.com/next", page.main_frame)
    asyncio.run(handler(second))
    assert second.fulfilled is None and second.fell_back


# --- bounded page.evaluate in the poll loops -----------------------------


class _HungPage:
    """page.evaluate never returns: hung page JavaScript."""

    def __init__(self, frames=()):
        self.frames = list(frames)
        self.evaluations = 0
        self.mouse = SimpleNamespace(click=self._click)
        self.clicks = 0

    async def evaluate(self, *args, **kwargs):
        self.evaluations += 1
        await asyncio.Event().wait()

    async def _click(self, x, y):
        self.clicks += 1


def _timed(coro, guard=10):
    """Run coro under an outer guard (so a regression fails instead of hanging)."""

    async def runner():
        started = time.monotonic()
        result = await asyncio.wait_for(coro, guard)
        return result, time.monotonic() - started

    return asyncio.run(runner())


def test_U1_turnstile_poll_ends_at_deadline_when_page_js_hangs(monkeypatch):
    monkeypatch.setattr(turnstile, "DEADLINE_SECONDS", 1.0)
    page = _HungPage()
    token, elapsed = _timed(turnstile.TurnstileSolver()._poll_token(page))
    assert token is None
    assert page.evaluations >= 1
    assert elapsed < 1.0 + turnstile.MIN_EVAL_TIMEOUT + 0.5, elapsed


def test_U1_turnstile_container_lookup_bounded_by_deadline(monkeypatch):
    monkeypatch.setattr(turnstile, "DEADLINE_SECONDS", 1.0)
    monkeypatch.setattr(turnstile, "CLICK_AT_SECONDS", (0.0,))
    solver = turnstile.TurnstileSolver()

    async def no_token(page, deadline=None):
        return None

    solver._read_token = no_token
    page = _HungPage(frames=[SimpleNamespace(url="https://challenges.cloudflare.com/cdn-cgi/x")])
    token, elapsed = _timed(solver._poll_token(page))
    assert token is None
    assert page.evaluations == 1  # the container lookup hung, not skipped
    assert page.clicks == 0
    # one poll interval after the bounded lookup, then the deadline
    assert elapsed < 1.0 + turnstile.POLL_INTERVAL + turnstile.MIN_EVAL_TIMEOUT + 0.5, elapsed


def test_U1_hcaptcha_poll_ends_at_deadline_when_page_js_hangs(monkeypatch):
    monkeypatch.setattr(hcaptcha, "DEADLINE_SECONDS", 1.0)
    page = _HungPage()
    token, elapsed = _timed(hcaptcha.HcaptchaSolver()._poll_token(page))
    assert token is None
    assert page.evaluations >= 1
    assert elapsed < 1.0 + hcaptcha.MIN_EVAL_TIMEOUT + 0.5, elapsed


def test_U1_v3_wait_for_execute_ends_at_deadline_when_page_js_hangs():
    solver = recaptcha.RecaptchaV3Solver()
    page = _HungPage()
    found, elapsed = _timed(solver._wait_for_execute(page, 1.0))
    assert found is False
    assert elapsed < 1.0 + solver.MIN_EVAL_TIMEOUT + 0.5, elapsed


def test_U1_v3_has_execute_probe_is_bounded():
    solver = recaptcha.RecaptchaV3Solver()
    page = _HungPage()
    found, elapsed = _timed(solver._has_execute(page))
    assert found is False
    assert elapsed < solver.PROBE_TIMEOUT + 0.5, elapsed


# --- Turnstile click ------------------------------------------------------


def test_U1_turnstile_container_is_scrolled_into_view_before_measuring():
    js = turnstile.CONTAINER_JS
    assert "scrollIntoView" in js
    assert js.index("scrollIntoView") < js.index("getBoundingClientRect")


class _BoxPage:
    def __init__(self, frame_urls):
        self.frames = [SimpleNamespace(url=u) for u in frame_urls]
        self.clicked = []
        self.mouse = SimpleNamespace(click=self._click)

    async def evaluate(self, script, *args):
        return {"x": 10, "y": 900, "width": 300, "height": 65}

    async def _click(self, x, y):
        self.clicked.append((x, y))


@pytest.mark.parametrize(
    "frame_url",
    [
        "https://unrelated.example/?q=challenges.cloudflare.com",
        "https://challenges.cloudflare.com.evil.example/frame",
        "https://evil.example/challenges.cloudflare.com/frame",
        "about:blank",
        None,
    ],
)
def test_U1_turnstile_no_click_without_provider_host_frame(frame_url):
    page = _BoxPage([frame_url])
    assert asyncio.run(turnstile.TurnstileSolver()._click_checkbox(page)) is False
    assert page.clicked == []


def test_U1_turnstile_clicks_with_provider_host_frame():
    page = _BoxPage(["https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"])
    assert asyncio.run(turnstile.TurnstileSolver()._click_checkbox(page)) is True
    assert page.clicked == [(40.0, 932.5)]


# --- log redaction -------------------------------------------------------


def test_U1_redact_hides_long_token_and_keeps_short_text():
    from workers.task_worker import _redact

    token = "T" * 40
    assert _redact({"token": token, "text": "X7K2P"}) == {
        "token": "<40 chars>",
        "text": "X7K2P",
    }


def test_U1_redact_boundary_is_16_characters():
    from workers.task_worker import _redact

    assert _redact({"a": "x" * 16}) == {"a": "x" * 16}
    assert _redact({"a": "x" * 17}) == {"a": "<17 chars>"}


class _TokenSolver:
    """Stands in for a browser solver: a 40-character token, nothing else."""

    TOKEN = "1x00000000000000000000AA.DUMMY-TOKEN-0123456789"[:40]

    async def setup(self):
        pass

    async def solve(self, input_data):
        return {"token": self.TOKEN}

    async def cleanup(self):
        pass


def test_U1_worker_log_has_no_token_but_keeps_it_in_the_result(db, capsys):
    assert len(_TokenSolver.TOKEN) == 40
    worker = task_worker.TaskWorker()
    worker.solvers = {"turnstile": _TokenSolver()}
    task = Task(
        api_key_id=1,
        type="turnstile",
        input_data=json.dumps({"site_key": TURNSTILE_PASS_KEY, "page_url": PAGE_URL}),
    )
    db.add(task)
    db.commit()

    asyncio.run(worker.process_task(db, task))
    out = capsys.readouterr().out

    db.refresh(task)
    assert task.status == "solved"
    # the client still gets the real token, only the log is redacted
    assert json.loads(task.result) == {"token": _TokenSolver.TOKEN}
    assert f"Task {task.id} solved" in out
    assert _TokenSolver.TOKEN not in out
    assert "<40 chars>" in out
