"""Retention cleanup: purge rules, batching, space reclaim, worker integration.

Every test builds its own database file, so nothing here depends on the global
engine or on collection order. `legacy=True` mimics an old deployment: WAL and
busy_timeout, but no auto_vacuum - the database `reclaim_space` has to migrate.
"""
import ast
import asyncio
import inspect
import json
import os
import sqlite3
import textwrap
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import config as app_config
from app import database as app_database
from app.database import Base, get_db
from app.main import app
from app.models.api_key import APIKey, User
from app.models.stats import Stats
from app.models.task import Task
from workers.cleanup import purge_tasks, reclaim_space, run_cleanup

NOW = datetime(2026, 1, 10, 12, 0, 0)
BIG = "A" * (256 * 1024)
BODY = {"type": "image_text", "input_data": {"image": "aGVsbG8="}}


def make_engine(path, legacy=False, trace=None):
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        if not legacy:
            cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
        if trace is not None:
            dbapi_connection.set_trace_callback(trace.append)

    Base.metadata.create_all(bind=engine)
    return engine


def add_task(session, status, age, input_data="{}", now=NOW, **cols):
    task = Task(
        api_key_id=1,
        type="image_text",
        status=status,
        input_data=input_data,
        created_at=now - age,
        **cols,
    )
    session.add(task)
    session.flush()
    return task.id


def fill(engine, rows, status="solved", age=timedelta(hours=2), input_data=BIG, now=NOW):
    session = sessionmaker(bind=engine)()
    for _ in range(rows):
        add_task(session, status, age, input_data, now=now)
    session.commit()
    session.close()


def pragma(path, name):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"PRAGMA {name}").fetchone()[0]
    finally:
        conn.close()


def wal_size(path):
    wal = str(path) + "-wal"
    return os.path.getsize(wal) if os.path.exists(wal) else 0


def purge_defaults(engine):
    """purge_tasks with the retention values the code ships with."""
    return purge_tasks(engine, now=NOW, input_retention_hours=1, task_retention_days=7)


# ------------------------------------------------------------------- purge rules
def test_purge_only_touches_finished_tasks(tmp_path):
    engine = make_engine(tmp_path / "rules.db")
    session = sessionmaker(bind=engine)()
    ids = {
        "pending_8d": add_task(session, "pending", timedelta(days=8), BIG),
        "processing_8d": add_task(session, "processing", timedelta(days=8), BIG),
        "solved_8d": add_task(session, "solved", timedelta(days=8), BIG),
        "failed_8d": add_task(session, "failed", timedelta(days=8), BIG),
        "solved_2h": add_task(session, "solved", timedelta(hours=2), BIG),
    }
    session.commit()

    got = purge_defaults(engine)
    assert got == {"inputs_cleared": 1, "tasks_deleted": 2}, (
        f"only finished tasks may be purged: two old rows deleted, one input blanked, got {got}"
    )
    session.expire_all()
    assert session.get(Task, ids["solved_8d"]) is None, "an old solved task must be deleted"
    assert session.get(Task, ids["failed_8d"]) is None, "an old failed task must be deleted"
    for name in ("pending_8d", "processing_8d"):
        row = session.get(Task, ids[name])
        assert row is not None and row.input_data == BIG, (
            f"a {name} task is live work: it must keep both its row and its input"
        )
    assert session.get(Task, ids["solved_2h"]).input_data == "", (
        "a finished task older than the input retention must lose its input"
    )
    session.close()
    engine.dispose()


def test_purge_keeps_result_and_error_and_stats(tmp_path):
    engine = make_engine(tmp_path / "keep.db")
    session = sessionmaker(bind=engine)()
    solved = add_task(
        session, "solved", timedelta(hours=3), BIG, result=json.dumps({"token": "t1"})
    )
    failed = add_task(session, "failed", timedelta(hours=3), BIG, error_message="boom")
    session.add(
        Stats(total_tasks=7, solved_tasks=5, failed_tasks=2, total_solve_time_seconds=42)
    )
    session.commit()

    purge_defaults(engine)
    session.expire_all()
    assert session.get(Task, solved).result == '{"token": "t1"}', (
        "the solution must survive the input purge"
    )
    assert session.get(Task, failed).error_message == "boom", (
        "the failure reason must survive the input purge"
    )
    stats = session.query(Stats).one()
    assert (stats.total_tasks, stats.solved_tasks, stats.failed_tasks) == (7, 5, 2), (
        "cleanup must not touch the stats table"
    )
    session.close()
    engine.dispose()


def test_purge_is_idempotent(tmp_path):
    engine = make_engine(tmp_path / "twice.db")
    fill(engine, 3)
    assert purge_defaults(engine)["inputs_cleared"] == 3
    assert purge_defaults(engine) == {"inputs_cleared": 0, "tasks_deleted": 0}, (
        "a second round over an already cleaned database must find nothing"
    )
    engine.dispose()


def test_retention_defaults_are_read_from_settings(tmp_path, monkeypatch):
    engine = make_engine(tmp_path / "settings.db")
    session = sessionmaker(bind=engine)()
    task_id = add_task(session, "solved", timedelta(hours=5), BIG)
    session.commit()

    monkeypatch.setattr(app_config.settings, "input_retention_hours", 6)
    monkeypatch.setattr(app_config.settings, "task_retention_days", 7)
    assert purge_tasks(engine, now=NOW) == {"inputs_cleared": 0, "tasks_deleted": 0}

    monkeypatch.setattr(app_config.settings, "input_retention_hours", 4)
    assert purge_tasks(engine, now=NOW) == {"inputs_cleared": 1, "tasks_deleted": 0}, (
        "input_retention_hours must be taken from settings at call time"
    )
    monkeypatch.setattr(app_config.settings, "task_retention_days", 0.1)
    assert purge_tasks(engine, now=NOW) == {"inputs_cleared": 0, "tasks_deleted": 1}, (
        "task_retention_days must be taken from settings at call time"
    )
    session.expire_all()
    assert session.get(Task, task_id) is None
    session.close()
    engine.dispose()


# ------------------------------------------------------------------- boundaries
def test_delete_age_boundary_is_strict(tmp_path):
    engine = make_engine(tmp_path / "delete-boundary.db")
    session = sessionmaker(bind=engine)()
    exact = add_task(session, "solved", timedelta(days=7))
    older = add_task(session, "solved", timedelta(days=7, microseconds=1))
    session.commit()

    got = purge_defaults(engine)
    assert got == {"inputs_cleared": 1, "tasks_deleted": 1}, (
        f"a task exactly at its retention age must survive (the comparison is strict), got {got}"
    )
    session.expire_all()
    assert session.get(Task, exact) is not None
    assert session.get(Task, older) is None
    session.close()
    engine.dispose()


def test_input_age_boundary_is_strict(tmp_path):
    engine = make_engine(tmp_path / "input-boundary.db")
    session = sessionmaker(bind=engine)()
    exact = add_task(session, "solved", timedelta(hours=1), BIG)
    older = add_task(session, "solved", timedelta(hours=1, microseconds=1), BIG)
    session.commit()

    got = purge_defaults(engine)
    assert got == {"inputs_cleared": 1, "tasks_deleted": 0}, (
        f"an input exactly at its retention age must be kept (the comparison is strict), got {got}"
    )
    session.expire_all()
    assert session.get(Task, exact).input_data == BIG
    assert session.get(Task, older).input_data == ""
    session.close()
    engine.dispose()


# ------------------------------------------------------------------- batching
def _watch(engine, keyword):
    """Row counts of every statement starting with `keyword`, plus commits."""
    rowcounts, commits = [], []

    def after(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith(keyword):
            rowcounts.append(cursor.rowcount)

    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "commit", lambda conn: commits.append(1))
    return rowcounts, commits


def test_deletes_run_in_batches(tmp_path):
    engine = make_engine(tmp_path / "batch-delete.db")
    fill(engine, 250, status="failed", age=timedelta(days=9), input_data="x" * 100)
    rowcounts, commits = _watch(engine, "DELETE FROM TASKS")

    got = purge_defaults(engine)
    assert got == {"inputs_cleared": 0, "tasks_deleted": 250}, got
    assert rowcounts and max(rowcounts) <= 100, (
        f"every DELETE batch must stay within batch_size, rowcounts={rowcounts}"
    )
    assert len(rowcounts) >= 3, f"250 rows at 100 per batch need at least 3 DELETEs, got {rowcounts}"
    assert len(commits) >= 3, f"each batch must commit on its own, commits={len(commits)}"
    engine.dispose()


def test_input_updates_run_in_batches(tmp_path):
    engine = make_engine(tmp_path / "batch-update.db")
    fill(engine, 250, input_data="x" * 100)
    rowcounts, commits = _watch(engine, "UPDATE TASKS")

    got = purge_defaults(engine)
    assert got == {"inputs_cleared": 250, "tasks_deleted": 0}, got
    assert rowcounts and max(rowcounts) <= 100, (
        f"every UPDATE batch must stay within batch_size, rowcounts={rowcounts}"
    )
    assert len(rowcounts) >= 3, f"250 rows at 100 per batch need at least 3 UPDATEs, got {rowcounts}"
    assert len(commits) >= 3, f"each batch must commit on its own, commits={len(commits)}"
    engine.dispose()


# ------------------------------------------------------------------- database
def test_fresh_database_is_created_incremental(tmp_path):
    """The pragma only takes effect on a new database when it runs BEFORE
    journal_mode=WAL (measured on sqlite 3.46.1)."""
    path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", app_database._sqlite_pragmas)
    Base.metadata.create_all(bind=engine)
    engine.dispose()

    assert pragma(path, "auto_vacuum") == 2, (
        "a fresh database must be created with auto_vacuum=INCREMENTAL"
    )
    assert pragma(path, "journal_mode") == "wal", "the database must stay in WAL mode"


def test_reclaim_migrates_a_legacy_database(tmp_path):
    path = tmp_path / "legacy.db"
    trace = []
    engine = make_engine(path, legacy=True, trace=trace)
    assert pragma(path, "auto_vacuum") == 0

    fill(engine, 40)
    purge_defaults(engine)
    assert pragma(path, "freelist_count") > 1000, "the fixture must free real pages"
    trace.clear()
    reclaim_space(engine)

    assert pragma(path, "auto_vacuum") == 2, (
        "reclaim_space must migrate an old database to auto_vacuum=INCREMENTAL"
    )
    assert any(s.strip().upper().startswith("VACUUM") for s in trace), (
        "migrating a legacy database needs one full VACUUM"
    )
    assert pragma(path, "freelist_count") == 0, "the freelist must be empty after reclaim"
    assert os.path.getsize(path) < 1_000_000, os.path.getsize(path)
    engine.dispose()


def test_incremental_reclaim_empties_the_freelist(tmp_path):
    path = tmp_path / "incremental.db"
    trace = []
    engine = make_engine(path, legacy=True, trace=trace)
    fill(engine, 40)
    purge_defaults(engine)
    reclaim_space(engine)  # migration round: full VACUUM
    assert pragma(path, "auto_vacuum") == 2

    fill(engine, 40)
    purge_defaults(engine)
    assert pragma(path, "freelist_count") > 1000, "the fixture must free real pages"
    trace.clear()
    reclaim_space(engine)

    assert pragma(path, "freelist_count") == 0, (
        "incremental_vacuum must run to completion: one page per call leaves the file big"
    )
    assert not any(s.strip().upper().startswith("VACUUM") for s in trace), (
        "an INCREMENTAL database must never be fully VACUUMed again"
    )
    assert any("incremental_vacuum" in s.lower() for s in trace), trace
    assert os.path.getsize(path) < 1_000_000, os.path.getsize(path)
    engine.dispose()


def test_reclaim_truncates_the_wal(tmp_path):
    path = tmp_path / "wal.db"
    engine = make_engine(path, legacy=True)
    fill(engine, 40)
    purge_defaults(engine)
    assert wal_size(path) > 0, "the fixture must leave frames in the -wal file"

    reclaim_space(engine)
    assert wal_size(path) == 0, (
        "the -wal file must be truncated, otherwise a file-level backup still copies the old size"
    )
    engine.dispose()


def test_run_cleanup_defaults_to_the_app_engine(tmp_path, monkeypatch):
    engine = make_engine(tmp_path / "default.db")
    monkeypatch.setattr(app_database, "engine", engine)
    # run_cleanup() reads "now" itself, so the rows must be old in real time
    fill(engine, 2, now=datetime.utcnow())

    assert run_cleanup() == {"inputs_cleared": 2, "tasks_deleted": 0}, (
        "run_cleanup without an engine must clean the app's own database"
    )
    engine.dispose()


def test_run_cleanup_purges_before_it_reclaims(tmp_path):
    path = tmp_path / "order.db"
    trace = []
    engine = make_engine(path, legacy=True, trace=trace)
    fill(engine, 40, now=datetime.utcnow())

    assert run_cleanup(engine) == {"inputs_cleared": 40, "tasks_deleted": 0}
    vacuum_at = next(
        i for i, s in enumerate(trace) if s.strip().upper().startswith("VACUUM")
    )
    update_at = max(i for i, s in enumerate(trace) if s.lstrip().upper().startswith("UPDATE TASKS"))
    assert update_at < vacuum_at, (
        "the migration VACUUM must run over an already purged database, not before it"
    )
    assert pragma(path, "auto_vacuum") == 2
    assert os.path.getsize(path) < 1_000_000, os.path.getsize(path)
    engine.dispose()


# ------------------------------------------------------------------- GET after purge
@pytest.fixture
def http(tmp_path):
    engine = make_engine(tmp_path / "http.db")
    session = sessionmaker(bind=engine)()
    user = User(username="purge-get", password_hash="h", password_salt="s")
    session.add(user)
    session.commit()
    raw = APIKey.generate_key()
    session.add(APIKey(user_id=user.id, key_hash=APIKey.hash_key(raw)))
    session.commit()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session, engine, {"Authorization": f"Bearer {raw}"}
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_get_task_after_the_input_is_purged(http):
    client, session, engine, headers = http
    task_id = client.post("/api/v1/task", json=BODY, headers=headers).json()["task_id"]
    task = session.get(Task, task_id)
    task.status = "solved"
    task.result = json.dumps({"text": "abc"})
    task.created_at = datetime.utcnow() - timedelta(hours=3)
    task.solved_at = datetime.utcnow() - timedelta(hours=3)
    session.commit()

    assert purge_tasks(engine)["inputs_cleared"] >= 1, "the finished task must lose its input"
    session.expire_all()
    assert session.get(Task, task_id).input_data == ""

    got = client.get(f"/api/v1/task/{task_id}", headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "solved", "GET must keep working after the input is purged"
    assert got.json()["result"] == {"text": "abc"}


# ------------------------------------------------------------------- worker
def _run_maybe_cleanup(worker, stamps):
    async def sequence():
        return [await worker.maybe_cleanup(now=stamp) for stamp in stamps]

    return asyncio.run(sequence())


def test_maybe_cleanup_runs_on_interval(monkeypatch):
    import workers.task_worker as tw

    calls = []
    monkeypatch.setattr(tw, "run_cleanup", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(tw.settings, "cleanup_interval_seconds", 600)
    worker = tw.TaskWorker()

    ran = _run_maybe_cleanup(worker, [1000.0, 1599.0, 1600.0, 2200.0])
    assert ran == [True, False, True, True], (
        f"the first round runs at once, the next ones every cleanup_interval_seconds, got {ran}"
    )
    assert len(calls) == 3, (
        f"run_cleanup must be called exactly when maybe_cleanup returns True, calls={len(calls)}"
    )


def test_maybe_cleanup_runs_off_the_event_loop(monkeypatch):
    import workers.task_worker as tw

    on_main_thread = []

    def fake(*a, **k):
        on_main_thread.append(threading.current_thread() is threading.main_thread())

    monkeypatch.setattr(tw, "run_cleanup", fake)
    monkeypatch.setattr(tw.settings, "cleanup_interval_seconds", 600)
    _run_maybe_cleanup(tw.TaskWorker(), [1000.0])

    assert on_main_thread == [False], (
        "run_cleanup must run off the event-loop thread: a synchronous VACUUM there "
        "would stall the heartbeat until the liveness probe kills the pod"
    )


def test_maybe_cleanup_swallows_errors(monkeypatch):
    import workers.task_worker as tw

    def boom(*a, **k):
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(tw, "run_cleanup", boom)
    monkeypatch.setattr(tw.settings, "cleanup_interval_seconds", 600)
    worker = tw.TaskWorker()

    try:
        ran = _run_maybe_cleanup(worker, [1000.0, 1600.0])
    except Exception as exc:
        pytest.fail(
            f"a cleanup failure must stay inside maybe_cleanup, got {type(exc).__name__}: {exc}"
        )
    assert ran == [True, True], (
        "a failed round counts as a round too, so the next one waits the full interval"
    )


def test_worker_loop_calls_maybe_cleanup():
    import workers.task_worker as tw

    tree = ast.parse(textwrap.dedent(inspect.getsource(tw.TaskWorker.run)))
    found = any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "maybe_cleanup"
        for loop in (n for n in ast.walk(tree) if isinstance(n, ast.While))
        for node in ast.walk(loop)
    )
    assert found, "TaskWorker.run must await maybe_cleanup() inside its polling loop"
