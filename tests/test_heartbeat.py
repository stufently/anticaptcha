"""Worker liveness: the heartbeat keeps ticking during a long task."""
import asyncio
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401  registers the table
from app.models.task import Task
from workers import task_worker
from workers.heartbeat import beat, is_fresh, main


def read_stamp(path):
    """The heartbeat value, or None while the file does not exist yet."""
    try:
        with open(path, "r", encoding="ascii") as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


class SlowSolver:
    """A solve that takes about a second, like a real CAPTCHA task."""

    def __init__(self, delay=1.0):
        self.delay = delay

    async def setup(self):
        return None

    async def cleanup(self):
        return None

    async def solve(self, input_data):
        await asyncio.sleep(self.delay)
        return {"text": "SLOW"}


def test_heartbeat_updates_during_long_task(tmp_path, monkeypatch):
    """The stamp must keep moving while one task is being solved, otherwise a
    long solve looks like a dead worker to the liveness probe."""
    hb_path = tmp_path / "hb"
    monkeypatch.setattr(task_worker.settings, "worker_heartbeat_file", str(hb_path))
    monkeypatch.setattr(task_worker.settings, "worker_heartbeat_interval", 0.05)
    monkeypatch.setattr(task_worker.settings, "worker_poll_interval", 0.05)
    monkeypatch.setattr(task_worker, "init_db", lambda: None)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    task = Task(
        api_key_id=1, type="image_text", input_data=json.dumps({"image": "aGVsbG8="})
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr(task_worker, "SessionLocal", sessionmaker(bind=engine))

    async def no_setup(self):
        return None

    # The real setup_solvers would load OCR/YOLO models and overwrite the fake
    monkeypatch.setattr(task_worker.TaskWorker, "setup_solvers", no_setup)

    worker = task_worker.TaskWorker()
    worker.solvers = {"image_text": SlowSolver()}

    async def scenario():
        samples = []

        async def sampler():
            while True:
                await asyncio.sleep(0.02)
                samples.append(read_stamp(hb_path))

        sampler_task = asyncio.create_task(sampler())
        runner = asyncio.create_task(worker.run())
        await asyncio.sleep(1.4)  # longer than the solve
        worker.stop()
        await runner
        sampler_task.cancel()
        return samples

    samples = asyncio.run(scenario())
    db.refresh(task)
    db.close()

    assert task.status == "solved", f"the long task itself must succeed: {task.error_message}"
    distinct = len({s for s in samples if s is not None})
    assert distinct >= 3, (
        f"heartbeat must keep updating during a long task, saw {distinct} distinct stamps"
    )


def test_check_detects_stale_and_missing(tmp_path):
    fresh = tmp_path / "fresh"
    beat(str(fresh))

    stale = tmp_path / "stale"
    stale.write_text(repr(time.time() - 3600), encoding="ascii")

    missing = tmp_path / "missing"

    garbage = tmp_path / "garbage"
    garbage.write_text("not a number", encoding="ascii")

    assert main(["--check", "--max-age", "30", "--path", str(fresh)]) == 0, (
        "a fresh heartbeat must pass the check"
    )
    assert main(["--check", "--max-age", "30", "--path", str(stale)]) == 1, (
        "a stale heartbeat must fail the check"
    )
    assert main(["--check", "--max-age", "30", "--path", str(missing)]) == 1, (
        "a missing heartbeat file must fail the check"
    )
    assert main(["--check", "--max-age", "30", "--path", str(garbage)]) == 1, (
        "a non-numeric heartbeat must fail the check"
    )
    assert is_fresh(str(fresh), 30) is True, "is_fresh must accept a fresh stamp"
    assert is_fresh(str(stale), 30) is False, "is_fresh must reject a stale stamp"


def test_heartbeat_task_cancelled_on_exit(monkeypatch):
    """run() must not leave the heartbeat task behind when it dies."""
    started = []
    monkeypatch.setattr(task_worker, "init_db", lambda: None)
    monkeypatch.setattr(
        task_worker.TaskWorker, "recover_interrupted_tasks", lambda self: 0
    )

    async def fake_setup(self):
        return None

    monkeypatch.setattr(task_worker.TaskWorker, "setup_solvers", fake_setup)

    async def fake_loop(path, interval):
        started.append(asyncio.current_task())
        while True:
            await asyncio.sleep(0.01)

    monkeypatch.setattr(task_worker, "heartbeat_loop", fake_loop)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(task_worker, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(task_worker.settings, "worker_poll_interval", 0.01)

    async def scenario():
        worker = task_worker.TaskWorker()

        async def broken_cleanup():
            raise RuntimeError("cleanup exploded")

        worker.cleanup_solvers = broken_cleanup
        runner = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)  # the loop is up, so the heartbeat task exists
        worker.stop()
        with pytest.raises(RuntimeError):
            await runner
        return list(started)

    tasks = asyncio.run(scenario())
    assert len(tasks) == 1, f"run() must start exactly one heartbeat task, got {len(tasks)}"
    assert tasks[0].cancelled(), "the heartbeat task must be cancelled when run() exits"
