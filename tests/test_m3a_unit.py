"""M3a unit tests, no network: browser-solver input contract, widget page, log redaction.

Every test name carries U1 (milestone marker).
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401  registers api_keys table
from app.models.task import Task
from workers import task_worker
from workers.solvers.widget_page import (
    check_browser_input,
    install_widget_page,
    widget_html,
    widget_route_matcher,
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
    ],
    ids=["quote", "angle", "space", "too-long"],
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


@pytest.mark.parametrize("render_mode", ["iframe", "PAGE", "embed", 5])
def test_U1_check_browser_input_rejects_unknown_render_mode(render_mode):
    with pytest.raises(ValueError):
        check_browser_input(
            {"site_key": TURNSTILE_PASS_KEY, "page_url": PAGE_URL, "render_mode": render_mode}
        )


@pytest.mark.parametrize("render_mode", [None, ""])
def test_U1_check_browser_input_treats_absent_render_mode_as_page(render_mode):
    # the field is optional: an unset/empty value is "not provided", not invalid
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


# --- widget_route_matcher / install_widget_page --------------------------


def test_U1_widget_route_matcher_takes_exact_url_without_fragment():
    matcher = widget_route_matcher("https://example.com/p?a=1#x")
    assert callable(matcher)
    assert matcher("https://example.com/p?a=1") is True
    assert matcher("https://example.com/p?a=2") is False
    assert matcher("https://example.com/p/x") is False
    assert matcher("https://example.com/p?a=1&b=2") is False


def test_U1_widget_route_matcher_keeps_url_without_fragment():
    matcher = widget_route_matcher("https://example.com/p")
    assert matcher("https://example.com/p") is True
    assert matcher("https://example.com/p#y") is False


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.fulfilled = None

    async def fulfill(self, **kwargs):
        self.fulfilled = kwargs


class _FakePage:
    def __init__(self):
        self.routes = []

    async def route(self, url, handler):
        self.routes.append((url, handler))


def test_U1_install_widget_page_routes_with_predicate_and_fulfills_widget():
    page = _FakePage()
    asyncio.run(
        install_widget_page(page, "https://example.com/p?a=1#x", "turnstile", TURNSTILE_PASS_KEY)
    )
    assert len(page.routes) == 1
    matcher, handler = page.routes[0]
    # a string here would be a Playwright glob: its metacharacters widen the match
    assert not isinstance(matcher, str)
    assert callable(matcher)

    route = _FakeRoute("https://example.com/p?a=1")
    asyncio.run(handler(route))
    assert route.fulfilled["status"] == 200
    assert route.fulfilled["content_type"] == "text/html"
    assert TURNSTILE_PASS_KEY in route.fulfilled["body"]
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in route.fulfilled["body"]


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
