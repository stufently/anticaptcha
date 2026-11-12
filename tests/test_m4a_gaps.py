"""M4a-M survivor coverage and regression tests for action/context lifetimes.

Based on the independent suggested_tests.py supplied with the review.
Survivors: P01 P02 P03 A03 C03 X05 X08 X10 B04 B05 S05.
"""
import asyncio
import json
import socket
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.task import Task
from app.utils.browser import BrowserManager
from workers import task_worker
from workers.solvers import smartcaptcha
from workers.solvers.proxy import parse_proxy

TOKEN = "SMART-TOKEN-" + "x" * 80
PROXY = {'server': 'http://8.8.8.8:8080'}


# --------------------------------------------------------------------------
# P01 / P02 - the per-operation budget of _bounded
# --------------------------------------------------------------------------

async def _measure_bounded(deadline_offset):
    """Seconds _bounded needs to cut a roundtrip that never returns."""
    async def never():
        await asyncio.sleep(30)

    async def run():
        marker = smartcaptcha._deadline.set(time.monotonic() + deadline_offset)
        try:
            start = time.monotonic()
            with pytest.raises(asyncio.TimeoutError):
                await smartcaptcha._bounded(never())
            return time.monotonic() - start
        finally:
            smartcaptcha._deadline.reset(marker)

    return await run()


def test_bounded_floor_after_deadline_is_sub_second():
    """P01: a roundtrip started after the deadline is cut at the 0.5 s floor.

    The floor is what keeps a stalled renderer from stretching the solver's
    60 s deadline; with a 5 s floor every stuck lookup adds 5 s of wall time.
    """
    async def run():
        return await asyncio.wait_for(_measure_bounded(-10.0), 2)
    assert asyncio.run(run()) < 1.5


def test_bounded_spends_remaining_deadline_not_full_budget():
    """P02: with 1 s left on the clock a stuck roundtrip is cut at ~1 s.

    _bounded must shrink with the deadline; a constant budget lets the total
    wall time grow to (number of roundtrips x DEADLINE_SECONDS).
    """
    async def run():
        return await asyncio.wait_for(_measure_bounded(1.0), 2)
    assert asyncio.run(run()) < 1.5


# --------------------------------------------------------------------------
# P03 / A03 - the polling loop itself, on a recording page double
# --------------------------------------------------------------------------

class _NoElement:
    """Locator double: nothing is ever visible, nothing is ever there."""

    @property
    def first(self):
        return self

    def locator(self, selector):
        return self

    async def is_visible(self):
        return False

    async def count(self):
        return 0

    async def get_attribute(self, name):
        raise AssertionError(f'class of a missing element must not be read ({name})')


class _RecordingPage:
    """Page double that records every roundtrip the solver makes."""

    def __init__(self, token_delay=0.0):
        self.token_delay = token_delay
        self.token_reads = 0
        self.executes = 0
        self.roundtrips = []

    async def evaluate(self, script):
        if 'smart-token' in script:
            self.token_reads += 1
            self.roundtrips.append('read_token')
            await asyncio.sleep(self.token_delay)
            return None
        self.executes += 1
        self.roundtrips.append('execute')
        return True

    def locator(self, selector):
        self.roundtrips.append(f'locator:{selector}')
        return _NoElement()

    def frame_locator(self, selector):
        self.roundtrips.append(f'frame_locator:{selector}')
        return _NoElement()


def test_poll_makes_no_roundtrip_after_deadline(monkeypatch):
    """P03: when the token read itself outlives the deadline, polling stops.

    Without the deadline check after _read_token the loop keeps walking the
    page (challenge lookup, checkbox lookup, gestures) after the deadline it
    is supposed to honour. The token read takes 0.4 s of a 0.2 s deadline -
    inside the 0.5 s floor of _bounded, so it does return, and it returns late.
    """
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 0.2)
    page = _RecordingPage(token_delay=0.4)
    with pytest.raises(RuntimeError, match='no token'):
        asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page))
    assert page.roundtrips == ['read_token']


def test_invisible_execute_is_called_once(monkeypatch):
    """A03: window.smartCaptcha.execute() is one-shot, not once per poll.

    The invisible widget starts a scoring round per execute(); re-issuing it
    every 200 ms burns the client's quota and can reset the widget.
    """
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 1.0)
    monkeypatch.setattr(smartcaptcha, 'INVISIBLE_DELAY_SECONDS', 0.0)
    page = _RecordingPage()
    with pytest.raises(RuntimeError, match='no token'):
        asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page))
    assert page.executes == 1
    assert page.token_reads > 1


# --------------------------------------------------------------------------
# C03 - challenge body not rendered yet
# --------------------------------------------------------------------------

def test_challenge_kind_waits_for_rendered_body():
    """C03: an advanced-iframe with no .AdvancedCaptcha body yet means "unknown
    so far" (None), not a blocking read of the missing element's class.

    On a real page locator.get_attribute() on a missing element blocks until
    the bound expires, so one unloaded frame eats the whole deadline.
    """
    class RenderedNothing(_NoElement):
        async def is_visible(self):
            return True

    class Page:
        def locator(self, selector):
            return RenderedNothing()

        def frame_locator(self, selector):
            return _NoElement()

    assert asyncio.run(smartcaptcha.SmartCaptchaSolver()._challenge_kind(Page())) is None


# --------------------------------------------------------------------------
# X05 / X08 / X10 - parse_proxy rejections that must not depend on DNS
# --------------------------------------------------------------------------

def test_localhost_zone_rejected_before_dns(monkeypatch):
    """X05: any *.localhost name is private by definition, DNS or not."""
    def no_dns(*args, **kwargs):
        raise AssertionError('a .localhost proxy must be rejected before any DNS lookup')

    monkeypatch.setattr(socket, 'getaddrinfo', no_dns)
    for host in ['sub.localhost', 'sub.localhost.', 'deep.sub.localhost']:
        with pytest.raises(ValueError, match='must be public'):
            parse_proxy(f'http://u:secret@{host}:3128')


def test_proxy_rejects_path_query_and_fragment():
    """X08: anything beyond scheme://host:port is not a proxy endpoint."""
    for value in ['http://8.8.8.8:3128/proxy',
                  'http://8.8.8.8:3128/?next=1',
                  'http://8.8.8.8:3128/#top',
                  'socks5://8.8.8.8:1080/path']:
        with pytest.raises(ValueError, match='must not contain a path'):
            parse_proxy(value)


def test_proxy_rejects_whitespace_and_control_chars():
    """X10: a proxy string with whitespace/control chars is a client error.

    urlsplit() silently strips tabs/newlines/edge spaces, so without the
    explicit check such a value is accepted as a different, valid URL.
    """
    for value in ['http://8.8.8.8:3128 ',
                  ' http://8.8.8.8:3128',
                  'http://8.8.8.8:31\t28',
                  'http://8.8.8.8:3128\n']:
        with pytest.raises(ValueError, match='without whitespace'):
            parse_proxy(value)


# --------------------------------------------------------------------------
# B04 / B05 - the proxy context must not outlive the page it was made for
# --------------------------------------------------------------------------

def _manager_with_proxy_context(monkeypatch, page=None, page_error=None):
    manager = BrowserManager()
    page = page if page is not None else SimpleNamespace(close=AsyncMock())
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page, side_effect=page_error), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context),
                              new_page=AsyncMock(return_value=page))
    monkeypatch.setattr(manager, 'get_browser', AsyncMock(return_value=browser))
    return manager, context


def test_failed_new_page_closes_proxy_context(monkeypatch):
    """B04: a context whose page failed to open is closed, not leaked."""
    async def run():
        manager, context = _manager_with_proxy_context(
            monkeypatch, page_error=RuntimeError('chromium refused'))
        try:
            with pytest.raises(RuntimeError, match='chromium refused'):
                await manager.new_page(stealth=False, proxy=PROXY)
            context.close.assert_awaited_once()
            assert manager._proxy_contexts == {}
        finally:
            await manager.close()
    asyncio.run(run())


def test_stealth_failure_closes_proxy_context(monkeypatch):
    """B05: a failed stealth patch closes the page *and* its proxy context."""
    async def run():
        from app.utils import browser as browser_module
        monkeypatch.setattr(browser_module, 'HAS_STEALTH', True)
        manager, context = _manager_with_proxy_context(monkeypatch)
        manager._stealth = SimpleNamespace(
            apply_stealth_async=AsyncMock(side_effect=RuntimeError('stealth boom')))
        try:
            with pytest.raises(RuntimeError, match='stealth boom'):
                await manager.new_page(stealth=True, proxy=PROXY)
            context.close.assert_awaited_once()
            assert manager._proxy_contexts == {}
        finally:
            await manager.close()
    asyncio.run(run())


@pytest.mark.parametrize('fail_creation', [False, True])
def test_cancelled_context_creation_closes_when_ready(monkeypatch, fail_creation):
    """Cancellation must stay prompt while a shielded context finishes opening."""
    async def run():
        manager = BrowserManager()
        started, release, finished, closed = (asyncio.Event() for _ in range(4))
        context = SimpleNamespace(close=AsyncMock(side_effect=closed.set), new_page=AsyncMock())
        creation_cancelled = False

        async def create_context(**kwargs):
            nonlocal creation_cancelled
            started.set()
            try:
                await release.wait()
                if fail_creation:
                    raise RuntimeError('context creation failed')
                return context
            except asyncio.CancelledError:
                creation_cancelled = True
                raise
            finally:
                finished.set()

        browser = SimpleNamespace(new_context=create_context)
        monkeypatch.setattr(manager, 'get_browser', AsyncMock(return_value=browser))
        pending = asyncio.create_task(manager.new_page(stealth=False, proxy=PROXY))
        try:
            await asyncio.wait_for(started.wait(), 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, 0.5)
            assert not creation_cancelled
            assert not finished.is_set()
            release.set()
            await asyncio.wait_for(finished.wait(), 1)
            if not fail_creation:
                await asyncio.wait_for(closed.wait(), 1)
            # Closing the manager drains cleanup work for a late context.
            await asyncio.wait_for(manager.close(), 1)
            if not fail_creation:
                context.close.assert_awaited_once()
            context.new_page.assert_not_awaited()
            assert manager._proxy_contexts == {}
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await manager.close()
    asyncio.run(run())


class _ActionElement(_NoElement):
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def locator(self, selector):
        return _ActionElement(self.page, selector)

    async def count(self):
        return int('checkbox-iframe' in self.selector)

    async def is_visible(self):
        return self.selector == ('#js-button' if self.page.mode == 'checkbox'
                                 else '.SliderCaptcha [data-testid="thumb"]')

    async def scroll_into_view_if_needed(self):
        pass

    async def bounding_box(self):
        return {'x': 0, 'y': 0, 'width': 300, 'height': 40}

    async def click(self):
        await self.page.action()


class _ActionPage(_RecordingPage):
    """A gesture can stall independently of token reads on the main page."""
    def __init__(self, mode, *, token_after_action=False, move_error=False):
        super().__init__()
        self.mode = mode
        self.token_after_action = token_after_action
        self.move_error = move_error
        self.action_started = None
        self.attempts = []
        self.mouse = SimpleNamespace(move=self.move, down=self.noop, up=self.noop)

    async def evaluate(self, script):
        self.token_reads += 1
        if (self.token_after_action and self.action_started is not None
                and time.monotonic() - self.action_started >= 0.05):
            return TOKEN
        return None

    def locator(self, selector):
        return _ActionElement(self, selector)

    def frame_locator(self, selector):
        return _ActionElement(self, selector)

    async def noop(self):
        pass

    async def move(self, *args, **kwargs):
        await self.action()

    async def action(self):
        self.action_started = time.monotonic()
        self.attempts.append(self.action_started)
        if self.move_error:
            from playwright.async_api import Error
            raise Error('first move failed')
        await asyncio.Event().wait()


@pytest.mark.parametrize('mode', ['checkbox', 'slider'])
def test_stalled_action_rechecks_token(monkeypatch, mode):
    """An unclickable button/stalled mouse must not hide an already issued token."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 1)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 0.1)
    page = _ActionPage(mode, token_after_action=True)
    start = time.monotonic()
    assert asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page)) == TOKEN
    assert time.monotonic() - start < 0.8
    assert page.token_reads >= 2


@pytest.mark.parametrize('mode', ['checkbox', 'slider'])
def test_action_budget_never_exceeds_remaining_deadline(monkeypatch, mode):
    """The action cap must shrink when the poll has less than that cap left."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 0.05)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 1)
    page = _ActionPage(mode)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match='no token'):
        asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page))
    assert time.monotonic() - start < 0.3
    assert page.token_reads >= 2


def test_failed_first_slider_move_consumes_action_and_cooldown(monkeypatch):
    """The first mouse operation counts even when it fails before mouse.down."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 0.3)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 0.08)
    monkeypatch.setattr(smartcaptcha, 'POLL_INTERVAL', 0.01)
    monkeypatch.setattr(smartcaptcha, 'MAX_ACTIONS', 2)
    page = _ActionPage('slider', move_error=True)
    with pytest.raises(RuntimeError, match='no token'):
        asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page))
    assert len(page.attempts) == 2
    assert page.attempts[1] - page.attempts[0] >= 0.08


def test_deadline_error_uses_configured_seconds(monkeypatch):
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 0.2)
    with pytest.raises(RuntimeError, match=r'^SmartCaptcha: no token within 0\.2s$'):
        asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(_RecordingPage()))


def test_slider_stages_share_one_action_budget(monkeypatch):
    """Several individually fast mouse calls must not multiply the gesture cap."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 1)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 0.12)
    page = _ActionPage('slider', token_after_action=True)

    async def slow_mouse(*args, **kwargs):
        if page.action_started is None:
            page.action_started = time.monotonic()
        await asyncio.sleep(0.09)

    page.mouse = SimpleNamespace(move=slow_mouse, down=slow_mouse, up=slow_mouse)
    start = time.monotonic()
    assert asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page)) == TOKEN
    assert time.monotonic() - start < 0.25


def test_disabled_checkbox_does_not_hide_token(monkeypatch):
    """Chromium actionability waits on a disabled button while the token appears."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 1)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 0.1)

    async def run():
        manager = BrowserManager()
        try:
            page = await manager.new_page(stealth=False)
            await page.set_content('''<input name="smart-token" type="hidden">
                <iframe data-testid="checkbox-iframe" srcdoc='
                  <button id="js-button" disabled>Check</button>'></iframe>''')
            await page.frame_locator('iframe').locator('button').wait_for(state='visible')
            await page.evaluate('(token) => setTimeout(() => {document.querySelector("input").value = token}, 250)', TOKEN)
            start = time.monotonic()
            assert await smartcaptcha.SmartCaptchaSolver()._poll(page) == TOKEN
            assert time.monotonic() - start < 0.8
        finally:
            await manager.close()
    asyncio.run(run())


# --------------------------------------------------------------------------
# S05 - _strip_proxy on input that never carried a proxy
# --------------------------------------------------------------------------

def test_strip_proxy_returns_dict_without_proxy_unchanged():
    """S05: input_data without a proxy key is returned verbatim."""
    raw = json.dumps({'site_key': 'key', 'page_url': 'https://example.com/'})
    assert task_worker._strip_proxy(raw) == raw


def test_process_task_without_proxy_stays_solved(tmp_path, monkeypatch):
    """S05: every task type goes through _strip_proxy, proxy or not.

    Without the "'proxy' not in data" guard a solved VK/image_text task raises
    KeyError inside the success branch and is written back as failed.
    """
    engine = create_engine('sqlite:///' + str(tmp_path / 'tasks.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(task_worker, 'SessionLocal', factory)
    original = {'site_key': 'key', 'page_url': 'https://example.com/'}

    class Solver:
        async def solve(self, input_data):
            assert input_data == original
            return {'token': TOKEN}

    async def run():
        db = factory()
        try:
            worker = task_worker.TaskWorker()
            worker.solvers['yandex_smartcaptcha'] = Solver()
            task = Task(api_key_id=1, type='yandex_smartcaptcha',
                        input_data=json.dumps(original))
            db.add(task)
            db.commit()
            await worker.process_task(db, task)
            db.refresh(task)
            assert task.status == 'solved'
            assert json.loads(task.input_data) == original
        finally:
            db.close()
            engine.dispose()
    asyncio.run(run())


def test_stalled_mouse_up_is_bounded_and_always_attempted(monkeypatch):
    """The release runs even after the drag stalls, but cannot hold the poll."""
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 10)
    monkeypatch.setattr(smartcaptcha, 'ACTION_WAIT_SECONDS', 0.1)
    monkeypatch.setattr(smartcaptcha, 'MOUSE_UP_SECONDS', 0.2)
    page = _ActionPage('slider', token_after_action=True)
    released = []

    async def fast(*args, **kwargs):
        if page.action_started is None:
            page.action_started = time.monotonic()

    async def stalled_move(*args, **kwargs):
        if page.action_started is not None:
            await asyncio.Event().wait()
        page.action_started = time.monotonic()

    async def stalled_up(*args, **kwargs):
        released.append(time.monotonic())
        await asyncio.Event().wait()

    page.mouse = SimpleNamespace(move=stalled_move, down=fast, up=stalled_up)
    start = time.monotonic()
    assert asyncio.run(smartcaptcha.SmartCaptchaSolver()._poll(page)) == TOKEN
    assert released, 'mouse.up was not attempted after a stalled drag'
    assert time.monotonic() - start < 1.0
