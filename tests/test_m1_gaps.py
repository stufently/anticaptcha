"""Gaps left by M1: mutation survivors plus the D1/D2/J1/R/B defects."""
import asyncio
import contextlib
import io
import math
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

import pytest
from PIL import Image

sys.path.insert(0, "/app/tests")
from test_image_limits import png_header
from test_browser_reconnect import FakeBrowser, FakeChromium, install_fake
from test_vision_llm_sandbox import FakeProcess, install_fake_exec, make_classifier
from workers.solvers.image_text import check_image_dimensions
from workers import heartbeat, task_worker
from app.utils.browser import BrowserManager


class EmptySession:
    """`SessionLocal` stand-in whose query chain always ends with `None`."""

    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return None

    def close(self):
        pass


class HangingProcess(FakeProcess):
    """A qwen child that never answers, so the caller can cancel it."""

    def __init__(self):
        super().__init__()
        self.communicating = asyncio.Event()

    async def communicate(self):
        self.communicating.set()
        await asyncio.Event().wait()


def test_C03_vertical_side_limit():
    with pytest.raises(ValueError, match="Image too large:"):
        check_image_dimensions(png_header(10, 4097))


def test_C04_default_pixel_limit_rejects_five_million():
    with pytest.raises(ValueError, match="Image too large:"):
        check_image_dimensions(png_header(2500, 2000))


def test_C06_default_pixel_limit_accepts_four_million():
    try:
        dimensions = check_image_dimensions(png_header(2000, 2000))
    except ValueError as exc:
        pytest.fail(f"default pixel limit must accept 4 million pixels: {exc}")
    assert dimensions == (2000, 2000)


def test_C10_heartbeat_cancelled_before_run_returns(monkeypatch):
    async def no_setup(self):
        pass

    class EmptyDB:
        def query(self, *args):
            return self
        def filter(self, *args):
            return self
        def order_by(self, *args):
            return self
        def first(self):
            return None
        def close(self):
            pass

    monkeypatch.setattr(task_worker, "init_db", lambda: None)
    monkeypatch.setattr(task_worker.TaskWorker, "recover_interrupted_tasks", lambda self: 0)
    monkeypatch.setattr(task_worker.TaskWorker, "setup_solvers", no_setup)
    monkeypatch.setattr(task_worker.TaskWorker, "cleanup_solvers", no_setup)
    monkeypatch.setattr(task_worker, "SessionLocal", EmptyDB)
    monkeypatch.setattr(task_worker.settings, "worker_poll_interval", 0.01)

    async def scenario():
        started = asyncio.Event()
        beats = []

        async def fake_loop(path, interval):
            beats.append(asyncio.current_task())
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(task_worker, "heartbeat_loop", fake_loop)
        worker = task_worker.TaskWorker()
        runner = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            worker.stop()
            await asyncio.wait_for(runner, timeout=2)
            assert len(beats) == 1
            assert beats[0].done() and beats[0].cancelled()
        finally:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
            for beat in beats:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat

    asyncio.run(scenario())


def test_C13_cli_respects_custom_max_age(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat"
    path.write_text("50", encoding="ascii")
    monkeypatch.setattr(heartbeat.time, "time", lambda: 100.0)
    assert heartbeat.main(["--check", "--max-age", "60", "--path", str(path)]) == 0
    assert heartbeat.main(["--check", "--max-age", "40", "--path", str(path)]) == 1


def test_C14_exact_max_age_is_fresh(tmp_path):
    path = tmp_path / "heartbeat"
    path.write_text("70", encoding="ascii")
    assert heartbeat.is_fresh(str(path), max_age=30, now=100.0) is True


def test_C15_cli_uses_settings_path(monkeypatch):
    calls = []
    monkeypatch.setattr(heartbeat.settings, "worker_heartbeat_file", "/tmp/custom-heartbeat")

    def fake_is_fresh(path, age):
        calls.append((path, age))
        return True

    monkeypatch.setattr(heartbeat, "is_fresh", fake_is_fresh)
    assert heartbeat.main(["--check", "--max-age", "45"]) == 0
    assert calls == [("/tmp/custom-heartbeat", 45.0)]


def test_C16_liveness_command_rejects_stale_stamp(tmp_path):
    text = pathlib.Path("/app/chart/templates/deployment.yaml").read_text()
    worker = text.split('command: ["python", "-m", "workers.task_worker"]', 1)[1]
    block = worker.split("          livenessProbe:\n", 1)[1].split("            periodSeconds:", 1)[0]
    argv = re.findall(r"^                - (.+)$", block, flags=re.M)
    argv = ["300" if token.startswith("{{") else token for token in argv]
    path = tmp_path / "heartbeat"
    path.write_text("0", encoding="ascii")
    proc = subprocess.run(argv, env={**os.environ, "ANTICAPTCHA_WORKER_HEARTBEAT_FILE": str(path)},
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_C18_disconnect_clears_context(monkeypatch):
    install_fake(monkeypatch)
    manager = BrowserManager()

    async def scenario():
        browser = await manager.get_browser()
        manager._context = object()
        browser.fire("disconnected", browser)
        assert manager._context is None

    asyncio.run(scenario())


def test_C26_python_timeout_remains_bounded(monkeypatch):
    classifier = make_classifier(monkeypatch)
    install_fake_exec(monkeypatch, FakeProcess())
    timeouts = []

    async def fake_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    try:
        assert asyncio.run(classifier.classify_tiles(b"image", "bicycles")) == [0, 3]
        assert timeouts == [90.0]
    finally:
        classifier.cleanup()


def test_C27_attached_path_contains_original_image(monkeypatch):
    classifier = make_classifier(monkeypatch)
    attached = []
    payload = b"exact-original-image-bytes"

    async def fake_exec(*cmd, **kwargs):
        prompt = cmd[cmd.index("-m") + 2]
        reference = next(token for token in prompt.split() if token.startswith("@"))
        attached.append(pathlib.Path(reference[1:].rstrip(".")).read_bytes())
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    try:
        assert asyncio.run(classifier.classify_tiles(payload, "bicycles")) == [0, 3]
        assert attached == [payload]
    finally:
        classifier.cleanup()


def test_D1_rejects_nonfinite_and_far_future(tmp_path):
    """`inf`/`nan`/a wild future stamp must not keep the probe happy forever."""
    for stamp, expected in ((math.inf, False), (math.nan, False), (10000, False), (120, True)):
        path = tmp_path / "heartbeat"
        path.write_text(repr(float(stamp)), encoding="ascii")
        fresh = heartbeat.is_fresh(str(path), max_age=30, now=100)
        assert fresh is expected, f"stamp {stamp!r} at now=100, max_age=30: got {fresh}"


def test_D2_cancel_kills_and_waits_child(monkeypatch):
    classifier = make_classifier(monkeypatch)

    async def scenario():
        child = HangingProcess()
        install_fake_exec(monkeypatch, child)
        runner = asyncio.create_task(classifier.classify_tiles(b"image", "bicycles"))
        try:
            await asyncio.wait_for(child.communicating.wait(), timeout=5)
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await runner
        finally:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        leftovers = sorted(p.name for p in classifier.temp_dir.glob("captcha_*.png"))
        return child, leftovers

    try:
        child, leftovers = asyncio.run(scenario())
    finally:
        classifier.cleanup()

    assert child.killed, "cancelling the call must kill the qwen child"
    assert child.waited, "the killed child must be reaped, not left as a zombie"
    assert leftovers == [], f"the temp captcha image must be gone: {leftovers}"


def test_D2_timeout_kills_and_waits_child(monkeypatch):
    classifier = make_classifier(monkeypatch)
    child = FakeProcess(exc=asyncio.TimeoutError())
    install_fake_exec(monkeypatch, child)
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(classifier.classify_tiles(b"image", "bicycles"))
    finally:
        classifier.cleanup()

    assert child.killed, "a timed out qwen child must be killed"
    assert child.waited, "the killed child must be reaped, not left as a zombie"


def test_J1_rejects_jpeg2000_and_tiff():
    """Pillow and OpenJPEG disagree about which header wins in JP2/TIFF, so a
    tiny file can pass the size check and expand on decode."""
    for fmt in ("JPEG2000", "TIFF"):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, format=fmt)
        with pytest.raises(ValueError, match="Unsupported image format"):
            check_image_dimensions(buffer.getvalue())

    for fmt in ("PNG", "JPEG", "WEBP", "BMP"):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, format=fmt)
        assert check_image_dimensions(buffer.getvalue()) == (8, 8), f"{fmt} must stay accepted"


def test_R1_recovery_retried_until_success(monkeypatch):
    """A locked database at startup must not strand `processing` tasks forever."""
    calls = []

    def flaky_recover(self):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return 0

    async def no_setup(self):
        pass

    async def fake_loop(path, interval):
        await asyncio.Event().wait()

    monkeypatch.setattr(task_worker, "init_db", lambda: None)
    monkeypatch.setattr(task_worker.TaskWorker, "recover_interrupted_tasks", flaky_recover)
    monkeypatch.setattr(task_worker.TaskWorker, "setup_solvers", no_setup)
    monkeypatch.setattr(task_worker.TaskWorker, "cleanup_solvers", no_setup)
    monkeypatch.setattr(task_worker, "SessionLocal", EmptySession)
    monkeypatch.setattr(task_worker, "heartbeat_loop", fake_loop)
    monkeypatch.setattr(task_worker.settings, "worker_poll_interval", 0.01)

    async def scenario():
        worker = task_worker.TaskWorker()
        runner = asyncio.create_task(worker.run())
        try:
            await asyncio.sleep(0.3)  # dozens of loop iterations at 0.01s polling
            worker.stop()
            await asyncio.wait_for(runner, timeout=5)
        finally:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner

    asyncio.run(scenario())

    assert calls == [1, 2], (
        f"recovery must be retried until it succeeds and then stop, got calls {calls}"
    )


def test_B1_concurrent_get_browser_launches_once(monkeypatch):
    """Two callers at once must not both start a Chromium."""
    fake = install_fake(monkeypatch)
    launches = []

    async def yielding_launch(self, **kwargs):
        launches.append(kwargs)
        await asyncio.sleep(0)  # the window a second caller slips through
        browser = FakeBrowser(f"browser-{len(launches)}")
        self.launched.append(browser)
        return browser

    monkeypatch.setattr(FakeChromium, "launch", yielding_launch)
    manager = BrowserManager()

    async def scenario():
        return await asyncio.gather(manager.get_browser(), manager.get_browser())

    first, second = asyncio.run(scenario())

    assert len(launches) == 1, f"concurrent get_browser must launch once, got {len(launches)}"
    assert first is second, "both callers must receive the same browser"
    assert fake.starts == 1, f"one driver start is enough, got {fake.starts}"
