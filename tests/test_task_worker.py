"""TaskWorker: a solver failing in setup() must not take the worker down."""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
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
