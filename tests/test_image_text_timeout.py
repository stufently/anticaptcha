"""Synchronous OCR must not defeat the task timeout or run concurrently."""
import asyncio
import json
import threading
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401
from app.models.task import Task
from workers import task_worker
from workers.solvers.image_text import ImageTextSolver


class SlowReader:
    """First call blocks like a long readtext(); later calls are fast."""

    def __init__(self, first_delay):
        self.first_delay = first_delay
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.finished = threading.Event()
        self._guard = threading.Lock()

    def readtext(self, image):
        with self._guard:
            self.calls += 1
            n = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if n == 1:
                time.sleep(self.first_delay)  # blocking, like real OCR
                return [(None, "LATE", 0.9)]
            return [(None, "ABC123", 0.9)]
        finally:
            with self._guard:
                self.active -= 1
            if n == 1:
                self.finished.set()


def test_ocr_timeout_does_not_block_loop_and_does_not_overlap(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    solver = ImageTextSolver()
    reader = SlowReader(first_delay=2.0)
    solver.reader = reader
    monkeypatch.setattr(solver, "_preprocess_image", lambda b: b)
    w = task_worker.TaskWorker()
    w.solvers = {"image_text": solver}

    def add():
        t = Task(api_key_id=1, type="image_text", input_data=json.dumps({"image": "aGVsbG8="}))
        db.add(t)
        db.commit()
        return t

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        tick_task = asyncio.create_task(ticker())
        monkeypatch.setattr(task_worker.settings, "task_timeout", 0.5)
        t1 = add()
        start = time.monotonic()
        await w.process_task(db, t1)
        elapsed = time.monotonic() - start
        ticks_during_t1 = ticks

        # second task waits for the first OCR thread (lock), then succeeds
        monkeypatch.setattr(task_worker.settings, "task_timeout", 10)
        t2 = add()
        await w.process_task(db, t2)
        tick_task.cancel()
        return t1, t2, elapsed, ticks_during_t1

    t1, t2, elapsed, ticks = asyncio.run(scenario())
    assert reader.finished.is_set()  # the late thread did finish ...
    db.refresh(t1)
    db.refresh(t2)
    assert t1.status == "failed"  # ... but its result was dropped
    assert t1.error_message == "Task timed out after 0.5s"
    assert t1.result is None
    assert 0.4 <= elapsed < 1.5
    assert ticks >= 5  # event loop kept running during the blocking OCR
    assert t2.status == "solved"
    assert json.loads(t2.result) == {"text": "ABC123"}
    assert reader.max_active == 1  # no concurrent readtext()
    db.close()
