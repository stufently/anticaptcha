"""Worker start: tasks stuck in `processing` become failed; OCR is not quantized."""
import json
import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401
from app.models.task import Task
from workers import task_worker


def test_processing_tasks_failed_on_start_not_requeued(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(task_worker, "SessionLocal", Session)

    db = Session()
    for status in ("processing", "processing", "pending", "solved"):
        db.add(Task(api_key_id=1, type="image_text", status=status, input_data=json.dumps({})))
    db.commit()
    db.close()

    assert task_worker.TaskWorker().recover_interrupted_tasks() == 2

    db = Session()
    rows = [(t.status, t.error_message) for t in db.query(Task).order_by(Task.id)]
    db.close()
    assert rows == [
        ("failed", "worker restarted while processing the task"),
        ("failed", "worker restarted while processing the task"),
        ("pending", None),
        ("solved", None),
    ]


def test_run_recovers_before_solvers_and_loop(monkeypatch):
    import asyncio
    calls = []
    w = task_worker.TaskWorker()
    monkeypatch.setattr(task_worker, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(w, "recover_interrupted_tasks", lambda: calls.append("recover"))

    class Stop(Exception):
        pass

    async def fake_setup():
        calls.append("setup")
        raise Stop()  # end run() before the polling loop

    monkeypatch.setattr(w, "setup_solvers", fake_setup)
    try:
        asyncio.run(w.run())
    except Stop:
        pass
    # init_db first: recovery queries the tasks table, which may not exist yet
    assert calls == ["init_db", "recover", "setup"]


def test_easyocr_reader_not_quantized(monkeypatch):
    """Quantized LSTM kernels need AVX2/FMA -> SIGILL on older CPUs."""
    import asyncio
    from workers.solvers.image_text import ImageTextSolver

    seen = {}

    class FakeReader:
        def __init__(self, *args, **kwargs):
            seen["args"], seen["kwargs"] = args, kwargs

    monkeypatch.setitem(sys.modules, "easyocr", types.SimpleNamespace(Reader=FakeReader))
    solver = ImageTextSolver()
    asyncio.run(solver.setup())
    assert isinstance(solver.reader, FakeReader)
    assert seen["kwargs"].get("quantize") is False
    assert seen["kwargs"].get("download_enabled") is False
