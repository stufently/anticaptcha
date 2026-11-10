"""TaskWorker: a solver failing in setup() must not take the worker down."""
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


class BrokenSolver:
    async def setup(self):
        raise FileNotFoundError("weights missing for broken solver")

    async def solve(self, input_data):  # pragma: no cover - must never be called
        raise AssertionError("broken solver must not be registered")


class GoodSolver:
    async def setup(self):
        pass

    async def solve(self, input_data):
        return {"text": "ok"}


@pytest.fixture
def db():
    # StaticPool: one shared in-memory DB, also from other threads
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


@pytest.fixture
def worker(monkeypatch, capsys):
    # Broken first: without per-solver isolation its exception aborts the loop
    # before the good solver is registered.
    monkeypatch.setattr(
        task_worker, "SOLVERS", {"broken": BrokenSolver, "good": GoodSolver}
    )
    w = task_worker.TaskWorker()
    asyncio.run(w.setup_solvers())
    return w


def _task(db, task_type):
    task = Task(api_key_id=1, type=task_type, input_data=json.dumps({}))
    db.add(task)
    db.commit()
    return task


def test_broken_solver_skipped_others_registered(worker, capsys):
    assert set(worker.solvers) == {"good"}
    out = capsys.readouterr().out
    assert "broken" in out
    assert "FileNotFoundError" in out
    assert "weights missing for broken solver" in out


def test_task_of_unregistered_type_fails_not_pending(worker, db):
    task = _task(db, "broken")
    asyncio.run(worker.process_task(db, task))
    db.refresh(task)
    assert task.status == "failed"
    assert task.error_message == "No solver for task type: broken"


def test_task_of_registered_type_still_solved(worker, db):
    task = _task(db, "good")
    asyncio.run(worker.process_task(db, task))
    db.refresh(task)
    assert task.status == "solved"
    assert json.loads(task.result) == {"text": "ok"}
    # first solved task on a fresh DB creates the stats row
    stats = db.query(task_worker.Stats).one()
    assert (stats.total_tasks, stats.solved_tasks) == (1, 1)


class HangingSolver:
    """Stands in for a page.evaluate() Promise that never resolves."""

    def __init__(self):
        self.cleaned_up = False

    async def setup(self):
        pass

    async def solve(self, input_data):
        try:
            await asyncio.sleep(3600)
        finally:
            # mirrors the solvers' `finally: await page.close()`
            self.cleaned_up = True


def test_hanging_task_times_out_and_next_task_runs(monkeypatch, db):
    monkeypatch.setattr(task_worker.settings, "task_timeout", 0.2)
    hanging = HangingSolver()
    w = task_worker.TaskWorker()
    w.solvers = {"hang": hanging, "good": GoodSolver()}

    async def scenario():
        t1 = _task(db, "hang")
        t2 = _task(db, "good")
        await asyncio.wait_for(w.process_task(db, t1), timeout=5)
        await asyncio.wait_for(w.process_task(db, t2), timeout=5)
        return t1, t2

    t1, t2 = asyncio.run(scenario())
    db.refresh(t1)
    db.refresh(t2)
    assert t1.status == "failed"
    assert t1.error_message == "Task timed out after 0.2s"
    assert hanging.cleaned_up  # cancellation ran the solver's finally (page.close)
    assert t2.status == "solved"


def test_default_task_timeout_is_120s():
    from app.config import Settings
    assert Settings().task_timeout == 120


class SwallowingSolver:
    """turnstile pattern: an except around page.evaluate() inside the loop.
    With a bare `except:` it would swallow CancelledError and never stop."""

    async def setup(self):
        pass

    async def solve(self, input_data):
        while True:
            try:
                await asyncio.sleep(0.05)  # stands in for page.evaluate()
            except Exception:
                pass


def test_solver_catching_exception_still_cancelled_on_timeout(monkeypatch, db):
    import time
    monkeypatch.setattr(task_worker.settings, "task_timeout", 0.3)
    w = task_worker.TaskWorker()
    w.solvers = {"swallow": SwallowingSolver()}
    import threading
    task = _task(db, "swallow")
    # Own thread + join timeout: if cancellation is swallowed the loop never
    # ends (even an outer wait_for can't stop it), the test must fail, not hang.
    runner = threading.Thread(
        target=lambda: asyncio.run(w.process_task(db, task)), daemon=True
    )
    start = time.monotonic()
    runner.start()
    runner.join(timeout=3)
    assert not runner.is_alive(), "solve was not cancelled: CancelledError swallowed"
    assert time.monotonic() - start < 1.3
    db.refresh(task)
    assert task.status == "failed"
    assert task.error_message == "Task timed out after 0.3s"


def test_no_bare_except_in_solvers():
    """Bare `except:` / `except BaseException` swallow asyncio.CancelledError."""
    import re
    from pathlib import Path
    root = Path(task_worker.__file__).resolve().parent.parent
    pattern = re.compile(r"^\s*except\s*(:|BaseException\b)", re.M)
    offenders = [
        f"{p.relative_to(root)}:{s[:m.start()].count(chr(10)) + 1}"
        for d in ("workers", "app")
        for p in sorted((root / d).rglob("*.py"))
        for s in [p.read_text(encoding="utf-8")]
        for m in pattern.finditer(s)
    ]
    assert offenders == []
