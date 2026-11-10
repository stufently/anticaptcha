"""BrowserManager must relaunch a dead Chromium instead of serving it forever."""
import asyncio

import pytest

from app.utils import browser as browser_module
from app.utils.browser import BrowserManager


class FakeBrowser:
    def __init__(self, name):
        self.name = name
        self.connected = True
        self.handlers = {}
        self.closed = False

    def is_connected(self):
        return self.connected

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def fire(self, event, *args):
        for handler in self.handlers.get(event, []):
            handler(*args)

    async def close(self):
        self.closed = True
        self.connected = False


class FakeChromium:
    def __init__(self, fail_launches):
        self.fail_launches = fail_launches
        self.launched = []

    async def launch(self, **kwargs):
        if self.fail_launches > 0:
            self.fail_launches -= 1
            raise RuntimeError("chromium.launch failed")
        browser = FakeBrowser(f"browser-{len(self.launched) + 1}")
        self.launched.append(browser)
        return browser


class FakeDriver:
    """What `async_playwright().start()` returns."""

    def __init__(self, fail_launches):
        self.chromium = FakeChromium(fail_launches)
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakePlaywright:
    """Stands in for `playwright.async_api.async_playwright`."""

    def __init__(self, fail_launches=0):
        self.fail_launches = fail_launches
        self.drivers = []
        self.starts = 0

    def __call__(self):
        return self

    async def start(self):
        self.starts += 1
        driver = FakeDriver(self.fail_launches)
        self.fail_launches = 0  # the failure budget belongs to the first driver
        self.drivers.append(driver)
        return driver

    @property
    def launches(self):
        return sum(len(d.chromium.launched) for d in self.drivers)


def install_fake(monkeypatch, fail_launches=0):
    fake = FakePlaywright(fail_launches)
    monkeypatch.setattr(browser_module, "async_playwright", fake)
    return fake


def test_disconnected_browser_is_relaunched(monkeypatch):
    """A browser whose connection died must not be handed out again."""
    fake = install_fake(monkeypatch)
    manager = BrowserManager()

    async def scenario():
        first = await manager.get_browser()
        first.connected = False  # died silently: no event, only is_connected() knows
        second = await manager.get_browser()
        return first, second

    first, second = asyncio.run(scenario())
    assert second is not first, "a disconnected browser must be relaunched, not reused"
    assert second.is_connected(), "the relaunched browser must be connected"
    assert fake.starts == 1, f"the running driver must be reused, got {fake.starts} starts"
    assert fake.launches == 2, f"exactly one relaunch is expected, got {fake.launches}"


def test_disconnect_event_resets_cached_browser(monkeypatch):
    """The `disconnected` event drops the cache even while is_connected() lies."""
    fake = install_fake(monkeypatch)
    manager = BrowserManager()

    async def scenario():
        first = await manager.get_browser()
        handlers = first.handlers.get("disconnected", [])
        for handler in handlers:
            handler(first)  # is_connected() is still True here
        cached_after_event = manager._browser
        second = await manager.get_browser()
        for handler in handlers:
            handler(first)  # a late event from the OLD browser
        cached_after_stale_event = manager._browser
        return handlers, cached_after_event, first, second, cached_after_stale_event

    handlers, cached_after_event, first, second, cached_after_stale_event = asyncio.run(
        scenario()
    )
    assert handlers, "get_browser must register a disconnected handler"
    assert cached_after_event is None, "the disconnect event must drop the cached browser"
    assert second is not first, "a new browser must be launched after the event"
    assert cached_after_stale_event is second, (
        "an event from an old browser must not drop the current one"
    )
    assert fake.starts == 1, f"the running driver must be reused, got {fake.starts} starts"


def test_connected_browser_is_reused(monkeypatch):
    """A healthy cached browser must not trigger a relaunch."""
    fake = install_fake(monkeypatch)
    manager = BrowserManager()

    async def scenario():
        first = await manager.get_browser()
        second = await manager.get_browser()
        return first, second

    first, second = asyncio.run(scenario())
    assert fake.launches == 1, f"a healthy cached browser must be reused, got {fake.launches} launches"
    assert second is first, "the same connected browser must be returned"
    assert fake.starts == 1, f"one driver start is enough, got {fake.starts}"


def test_launch_failure_restarts_driver(monkeypatch):
    """A failed launch must not leave a broken driver cached forever."""
    fake = install_fake(monkeypatch, fail_launches=1)
    manager = BrowserManager()

    async def scenario():
        with pytest.raises(RuntimeError):
            await manager.get_browser()
        after_failure = (manager._playwright, fake.drivers[0].stopped)
        browser = await manager.get_browser()
        return after_failure, browser

    (playwright_after_failure, first_driver_stopped), browser = asyncio.run(scenario())
    assert playwright_after_failure is None, "a failed launch must drop the driver"
    assert first_driver_stopped, "a failed launch must stop the driver it started"
    assert fake.starts == 2, f"the next call must start a fresh driver, got {fake.starts} starts"
    assert browser.is_connected(), "the retry must produce a working browser"
