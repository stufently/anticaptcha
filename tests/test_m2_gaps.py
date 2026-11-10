"""Gaps left by M2: the ten mutation survivors plus the F1/B1/V1/L1 defects.

`Q06`, `C07`-`C10` and `W03`-`W07` are the mutations an independent run found
no test for: a quota rejection that commits instead of rolling back, an ignored
`batch_size`, an explicit zero retention replaced by the default, and five ways
to break the cleanup scheduler. `F1` (settings with no lower bound), `B1` (an
unvalidated `batch_size`), `V1` (a migration VACUUM that ignores free space)
and `L1` (an `init_db()` that gives up after one `busy_timeout`) are the code
defects found next to them.

The helper functions come from the modules that already exercise the same code
(`tests/test_quota.py`, `tests/test_cleanup.py`), so a fixture here builds the
same database as the tests it complements.

The `L1` scenarios run in subprocesses with their own ANTICAPTCHA_DATABASE_PATH,
like `tests/test_task_ids.py`: app.database builds its engine at import time, so
another database path needs another process.
"""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from collections import namedtuple
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.tasks import create_task
from app.config import Settings, settings
from app.models.api_key import APIKey, User
from app.models.task import Task
from app.schemas.task import TaskCreate
from workers.cleanup import _has_room_for_vacuum, purge_tasks, reclaim_space


def load_helpers(name):
    """Execute a sibling test module and hand back its fixtures and helpers."""
    spec = importlib.util.spec_from_file_location(name, Path("/app/tests") / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qhelpers = load_helpers("test_quota")
chelpers = load_helpers("test_cleanup")
quota, BODY = qhelpers.quota, qhelpers.BODY
make_engine, fill, _watch, NOW = (
    chelpers.make_engine, chelpers.fill, chelpers._watch, chelpers.NOW)
purge_defaults, pragma = chelpers.purge_defaults, chelpers.pragma


# ---------------------------------------------------------------- Q06 quota
def test_Q06_rejection_rolls_back_pending_changes(quota, monkeypatch):
    """A 429 must leave the session exactly as it was: rollback, not commit."""
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 1)
    _, key_id = quota.make_key("rollback-user")
    with quota.Session() as db:
        key = db.get(APIKey, key_id)
        user = db.get(User, key.user_id)
        create_task(TaskCreate(**BODY), (key, user), db)

    with quota.Session() as db:
        key = db.get(APIKey, key_id)
        user = db.get(User, key.user_id)
        user_id = user.id
        user.username = "must-not-be-committed"
        with pytest.raises(HTTPException) as exc:
            create_task(TaskCreate(**BODY), (key, user), db)
        assert exc.value.status_code == 429

    with quota.Session() as db:
        assert db.get(User, user_id).username == "rollback-user", (
            "the changes pending on the session were committed by the rejection"
        )


# ------------------------------------------------------- C07/C08 batch_size
@pytest.mark.parametrize("operation,age,keyword", [
    ("delete", timedelta(days=9), "DELETE FROM TASKS"),
    ("input", timedelta(hours=2), "UPDATE TASKS"),
], ids=["C07", "C08"])
def test_custom_batch_size(tmp_path, operation, age, keyword):
    """An explicit batch_size is the batch size, not a hint."""
    engine = make_engine(tmp_path / "batch.db")
    try:
        fill(engine, 9, age=age, input_data="payload")
        counts, commits = _watch(engine, keyword)
        report = purge_tasks(engine, now=NOW, batch_size=3)
        assert report["tasks_deleted" if operation == "delete" else "inputs_cleared"] == 9
        assert counts == [3, 3, 3], counts
        assert len(commits) >= 3
    finally:
        engine.dispose()


# ------------------------------------------------- C09/C10 explicit zero
@pytest.mark.parametrize("kind", ["input", "task"], ids=["C09", "C10"])
def test_explicit_zero_retention(tmp_path, monkeypatch, kind):
    """0 passed by the caller means "purge everything", not "use settings"."""
    monkeypatch.setattr(settings, "input_retention_hours", 1)
    monkeypatch.setattr(settings, "task_retention_days", 7)
    engine = make_engine(tmp_path / "zero.db")
    try:
        fill(engine, 1, age=timedelta(minutes=1), input_data="payload")
        kwargs = {"input_retention_hours": 0} if kind == "input" else {"task_retention_days": 0}
        got = purge_tasks(engine, now=NOW, **kwargs)
        assert got == {
            "inputs_cleared": int(kind == "input"),
            "tasks_deleted": int(kind == "task"),
        }, got
    finally:
        engine.dispose()


# ------------------------------------------------------------- W03-W07 worker
def test_W03_first_call_at_low_uptime(monkeypatch):
    """The first round runs even when the monotonic clock is still near zero."""
    import workers.task_worker as tw
    calls = []
    monkeypatch.setattr(tw, "run_cleanup", lambda: calls.append(1))
    monkeypatch.setattr(settings, "cleanup_interval_seconds", 600)
    assert asyncio.run(tw.TaskWorker().maybe_cleanup(now=0.0)) is True
    assert calls == [1]


def test_W04_default_clock_is_monotonic(monkeypatch):
    """Without `now`, the scheduler reads time.monotonic, not the wall clock."""
    import workers.task_worker as tw
    calls = []
    monkeypatch.setattr(tw, "run_cleanup", lambda: calls.append(1))
    monkeypatch.setattr(settings, "cleanup_interval_seconds", 600)
    worker = tw.TaskWorker()

    async def scenario():
        monkeypatch.setattr(tw.time, "monotonic", lambda: 1000.0)
        monkeypatch.setattr(tw.time, "time", lambda: 10000.0)
        first = await worker.maybe_cleanup()
        # The wall clock jumps BACKWARDS by 1000 s, monotonic advances by 600.
        monkeypatch.setattr(tw.time, "monotonic", lambda: 1600.0)
        monkeypatch.setattr(tw.time, "time", lambda: 9000.0)
        second = await worker.maybe_cleanup()
        return first, second

    assert asyncio.run(scenario()) == (True, True)
    assert calls == [1, 1]


def test_W05_failure_respects_backoff(monkeypatch):
    """A failed round counts: retrying it every poll would spin the loop."""
    import workers.task_worker as tw
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("expected failure")

    monkeypatch.setattr(tw, "run_cleanup", boom)
    monkeypatch.setattr(settings, "cleanup_interval_seconds", 600)
    worker = tw.TaskWorker()

    async def scenario():
        return [await worker.maybe_cleanup(now=t) for t in (1000, 1001, 1599, 1600)]

    assert asyncio.run(scenario()) == [True, False, False, True]
    assert len(calls) == 2


def test_W06_configured_interval(monkeypatch):
    """The interval comes from settings, not from a literal 600."""
    import workers.task_worker as tw
    calls = []
    monkeypatch.setattr(tw, "run_cleanup", lambda: calls.append(1))
    monkeypatch.setattr(settings, "cleanup_interval_seconds", 10)
    worker = tw.TaskWorker()

    async def scenario():
        return [await worker.maybe_cleanup(now=t) for t in (1000, 1009, 1010)]

    assert asyncio.run(scenario()) == [True, False, True]
    assert len(calls) == 2


def test_W07_polling_really_calls_cleanup(monkeypatch):
    """The loop must AWAIT maybe_cleanup, not merely contain the call."""
    import workers.task_worker as tw
    worker = tw.TaskWorker()
    calls = []

    async def noop():
        pass

    async def cleanup():
        calls.append("cleanup")
        return True

    async def heartbeat(*args):
        await asyncio.Event().wait()

    def recover():
        worker._recovery_pending = False
        calls.append("recover")

    def first():
        worker.running = False
        calls.append("query")
        return None

    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = first
    monkeypatch.setattr(tw, "init_db", lambda: None)
    monkeypatch.setattr(tw, "SessionLocal", lambda: db)
    monkeypatch.setattr(tw, "heartbeat_loop", heartbeat)
    monkeypatch.setattr(settings, "worker_poll_interval", 0)
    monkeypatch.setattr(worker, "_try_recover", recover)
    monkeypatch.setattr(worker, "setup_solvers", noop)
    monkeypatch.setattr(worker, "cleanup_solvers", noop)
    monkeypatch.setattr(worker, "maybe_cleanup", cleanup)
    asyncio.run(worker.run())
    assert calls == ["recover", "cleanup", "query"], calls
    db.close.assert_called_once()


# ------------------------------------------------------------ F1 settings
# (field, a value below the bound, the bound itself)
BOUNDS = [
    ("max_active_tasks_per_key", -1, 0),
    ("cleanup_interval_seconds", 0, 1),
    ("input_retention_hours", -0.5, 0),
    ("task_retention_days", -1.5, 0),
]


@pytest.mark.parametrize("name,below,boundary", BOUNDS,
                         ids=[f"F1-{name}" for name, _, _ in BOUNDS])
def test_F1_a_value_below_the_bound_is_rejected(name, below, boundary):
    """A negative quota switches the limit off (`if limit > 0`), a negative
    retention moves the purge boundary into the future and deletes fresh rows,
    and a zero interval cleans on every poll - none of it may be configured."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(**{name: below})
    assert name in str(excinfo.value), (
        f"{name}={below} must be rejected by its own lower bound, got: {excinfo.value}"
    )


@pytest.mark.parametrize("name,below,boundary", BOUNDS,
                         ids=[f"F1-{name}" for name, _, _ in BOUNDS])
def test_F1_the_bound_itself_is_accepted(name, below, boundary):
    """The bounds are inclusive: 0 tasks, 1 s, 0 h and 0 d are all legal."""
    assert getattr(Settings(**{name: boundary}), name) == boundary


# ------------------------------------------------------------ B1 batch_size
@pytest.mark.parametrize("bad", [0, -1], ids=["B1-zero", "B1-minus-one"])
def test_B1_batch_size_below_one_is_rejected(tmp_path, bad):
    """LIMIT 0 purges nothing and reports success, LIMIT -1 removes the limit."""
    engine = make_engine(tmp_path / f"batch{bad}.db")
    try:
        fill(engine, 3, age=timedelta(days=9), input_data="payload")
        with pytest.raises(ValueError, match=f"batch_size must be >= 1, got {bad}"):
            purge_tasks(engine, now=NOW, input_retention_hours=1,
                        task_retention_days=7, batch_size=bad)

        session = sessionmaker(bind=engine)()
        rows = session.query(Task).all()
        assert len(rows) == 3, f"batch_size={bad} deleted {3 - len(rows)} rows"
        assert [row.input_data for row in rows] == ["payload"] * 3, (
            f"batch_size={bad} cleared an input"
        )
        session.close()
    finally:
        engine.dispose()


def test_B1_batch_size_one_trims_one_row_at_a_time(tmp_path):
    engine = make_engine(tmp_path / "batch1.db")
    try:
        fill(engine, 3, age=timedelta(days=9), input_data="payload")
        counts, commits = _watch(engine, "DELETE FROM TASKS")
        report = purge_tasks(engine, now=NOW, input_retention_hours=1,
                             task_retention_days=7, batch_size=1)
        assert report == {"inputs_cleared": 0, "tasks_deleted": 3}, report
        assert counts == [1, 1, 1], counts
        assert len(commits) >= 3, commits
    finally:
        engine.dispose()


# -------------------------------------------------------- V1 room for VACUUM
DiskUsage = namedtuple("DiskUsage", "total used free")


def _stub_free_space(monkeypatch, db_path, free_for_size):
    """Replace shutil.disk_usage with one whose `free` follows the real size."""

    def disk_usage(_target):
        size = sum(os.path.getsize(p) for p in (str(db_path), f"{db_path}-wal")
                   if os.path.exists(p))
        free = free_for_size(size)
        return DiskUsage(total=4 * size + free, used=3 * size, free=free)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)


def _legacy_with_freelist(tmp_path, name):
    """A pre-auto_vacuum database whose pages are freed but not returned."""
    path = tmp_path / name
    trace = []
    engine = make_engine(path, legacy=True, trace=trace)
    assert pragma(path, "auto_vacuum") == 0, "the fixture must be a legacy database"
    fill(engine, 40)
    purge_defaults(engine)
    assert os.path.getsize(path) > 1_000_000, "the fixture must be worth VACUUMing"
    return path, engine, trace


def test_V1_migration_is_skipped_without_room(tmp_path, monkeypatch, capsys):
    path, engine, trace = _legacy_with_freelist(tmp_path, "noroom.db")
    try:
        _stub_free_space(monkeypatch, path, lambda size: 2 * size - 1)
        trace.clear()
        try:
            reclaim_space(engine)
        except Exception as exc:
            pytest.fail(f"a missing VACUUM must be skipped, not raised: {exc}")

        assert "Not enough free space" in capsys.readouterr().out, (
            "skipping the migration must say so"
        )
        assert pragma(path, "auto_vacuum") == 0, "the migration must not have run"
        assert not any(s.strip().upper().startswith("VACUUM") for s in trace), trace
        assert os.path.getsize(path) > 1_000_000, (
            f"the file was rebuilt anyway: {os.path.getsize(path)}"
        )
        assert any("wal_checkpoint" in s.lower() for s in trace), (
            f"the -wal checkpoint must run even when the VACUUM is skipped: {trace}"
        )
    finally:
        engine.dispose()


def test_V1_migration_runs_with_room(tmp_path, monkeypatch):
    path, engine, trace = _legacy_with_freelist(tmp_path, "room.db")
    try:
        _stub_free_space(monkeypatch, path, lambda size: 2 * size + 1)
        trace.clear()
        reclaim_space(engine)
        assert pragma(path, "auto_vacuum") == 2, "the migration must run"
        assert any(s.strip().upper().startswith("VACUUM") for s in trace), trace
        assert os.path.getsize(path) < 1_000_000, os.path.getsize(path)
    finally:
        engine.dispose()


def test_V1_exactly_two_sizes_of_free_space_is_enough(tmp_path, monkeypatch):
    """`free >= 2 * size` is inclusive: a VACUUM needs one extra copy."""
    path, engine, _trace = _legacy_with_freelist(tmp_path, "boundary.db")
    try:
        _stub_free_space(monkeypatch, path, lambda size: 2 * size)
        reclaim_space(engine)
        assert pragma(path, "auto_vacuum") == 2, (
            "free space exactly equal to two database sizes must still migrate"
        )
    finally:
        engine.dispose()


def test_V1_a_database_without_a_file_needs_no_room():
    """:memory: (and an empty path) has no file to copy, so it always passes."""
    engine = create_engine("sqlite://")
    try:
        assert _has_room_for_vacuum(engine) is True
    finally:
        engine.dispose()


# -------------------------------------------------------------- L1 init_db
REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD_TIMEOUT = 180
# Longer than busy_timeout (5 s), so the first attempt is guaranteed to fail and
# the retry is what makes init_db() succeed.
LOCK_SECONDS = 8

LOCK_HOLDER = textwrap.dedent("""
    import sqlite3, sys, time
    conn = sqlite3.connect(sys.argv[1], timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("BEGIN IMMEDIATE")
    print("LOCKED", flush=True)
    time.sleep(float(sys.argv[2]))
    conn.rollback()
""")

# Both children below create the schema uncontended first and leave a connected
# connection in the pool, the way a process that already talked to the database
# does. init_db() then reaches BEGIN IMMEDIATE on it, which gives up after
# busy_timeout; a brand new connection would instead spend the sqlite3 connect
# timeout (30 s) inside the PRAGMAs of app.database._sqlite_pragmas (measured).
L1_PREAMBLE = textwrap.dedent("""
    import json, sys, time
    import app.models  # noqa: F401  registers every table
    import app.database as dbmod
    from app.database import engine

    dbmod.init_db()
    engine.connect().close()

    attempts = []
    once = dbmod._init_db_once
    start = time.monotonic()

    def counted():
        attempts.append(round(time.monotonic() - start, 2))
        return once()

    dbmod._init_db_once = counted

    def tables():
        with engine.connect() as conn:
            return sorted(row[0] for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"))

    def call(kwargs):
        global start
        sys.stdout.write("READY\\n"); sys.stdout.flush()
        sys.stdin.readline()
        start = time.monotonic()
        try:
            dbmod.init_db(**kwargs)
            return {"outcome": "ok", "error": ""}
        except BaseException as exc:
            return {"outcome": type(exc).__module__ + "." + type(exc).__name__,
                    "error": str(exc)[:200].replace("\\n", " | ")}
""")

L1_WAIT = L1_PREAMBLE + textwrap.dedent("""
    facts = call({})
    facts["attempts"] = attempts
    facts["elapsed"] = round(time.monotonic() - start, 2)
    facts["tables"] = tables()
    print(json.dumps(facts))
""")

L1_NO_WAIT = L1_PREAMBLE + textwrap.dedent("""
    facts = call({"lock_wait_seconds": 0})
    facts["attempts"] = attempts
    facts["elapsed"] = round(time.monotonic() - start, 2)
    print(json.dumps(facts))
""")

L1_OTHER_ERROR = textwrap.dedent("""
    import json, sys, time
    import app.models  # noqa: F401
    import app.database as dbmod
    from sqlalchemy.exc import OperationalError

    attempts = []

    def broken():
        attempts.append(1)
        raise OperationalError("BEGIN IMMEDIATE", {}, Exception("disk I/O error"))

    dbmod._init_db_once = broken
    sys.stdout.write("READY\\n"); sys.stdout.flush()
    sys.stdin.readline()
    start = time.monotonic()
    try:
        dbmod.init_db(lock_wait_seconds=60)
        facts = {"outcome": "ok", "error": ""}
    except BaseException as exc:
        facts = {"outcome": type(exc).__module__ + "." + type(exc).__name__,
                 "error": str(exc)[:200].replace("\\n", " | ")}
    facts["attempts"] = attempts
    facts["elapsed"] = round(time.monotonic() - start, 2)
    print(json.dumps(facts))
""")


def _child_env(db_path):
    env = dict(os.environ)
    env["ANTICAPTCHA_DATABASE_PATH"] = str(db_path)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{old}" if old else str(REPO_ROOT)
    return env


def _init_db_child(code, db_path, hold_seconds, what):
    """Run one child that calls init_db(), optionally against a held lock.

    The child prepares its database and prints READY first; the lock is taken
    only then and the go signal on stdin is what starts the measured init_db().
    Handshaking keeps the wait measured against the lock instead of against
    interpreter startup, which is what makes the timing reproducible.
    """
    target = subprocess.Popen(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=_child_env(db_path),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    holder = None
    try:
        ready = target.stdout.readline().strip()
        assert ready == "READY", f"{what}: child never got ready, printed {ready!r}"
        if hold_seconds is not None:
            holder = subprocess.Popen(
                [sys.executable, "-c", LOCK_HOLDER, str(db_path), str(hold_seconds)],
                cwd=str(REPO_ROOT), env=_child_env(db_path),
                stdout=subprocess.PIPE, text=True,
            )
            locked = holder.stdout.readline().strip()
            assert locked == "LOCKED", f"{what}: holder never locked, printed {locked!r}"
        target.stdin.write("\n")
        target.stdin.flush()
        out, err = target.communicate(timeout=CHILD_TIMEOUT)
    finally:
        if holder is not None:
            holder.kill()
            holder.wait(timeout=30)
        if target.poll() is None:
            target.kill()
            target.communicate(timeout=30)

    assert target.returncode == 0, (
        f"{what}: child rc={target.returncode}\n{(err or out).strip()[-1200:]}"
    )
    lines = [line for line in out.splitlines() if line.startswith("{")]
    assert lines, f"{what}: child printed no facts:\n{out.strip()[-800:]}"
    return json.loads(lines[-1])


def test_L1_init_db_waits_out_a_long_lock(tmp_path):
    """The other process' migration outlasts busy_timeout: init_db() retries."""
    facts = _init_db_child(L1_WAIT, tmp_path / "wait.db", LOCK_SECONDS,
                           "waiting init_db() child")

    assert facts["outcome"] == "ok", (
        f"init_db() must wait the write lock out, got {facts['outcome']}: {facts['error']}"
    )
    assert len(facts["attempts"]) >= 2, (
        f"the attempt that ran into busy_timeout must be retried, "
        f"attempts at {facts['attempts']} s"
    )
    assert facts["elapsed"] >= 5.0, (
        f"waiting out one busy_timeout takes at least 5 s, took {facts['elapsed']} s"
    )
    assert {"tasks", "users", "api_keys", "stats"} <= set(facts["tables"]), (
        f"the schema must be complete after the retry: {facts['tables']}"
    )


def test_L1_zero_wait_gives_up_after_one_attempt(tmp_path):
    """lock_wait_seconds=0 keeps the old behaviour: one attempt, then raise."""
    facts = _init_db_child(L1_NO_WAIT, tmp_path / "nowait.db", LOCK_SECONDS,
                           "lock_wait_seconds=0 child")

    assert facts["outcome"] == "sqlalchemy.exc.OperationalError", facts
    assert "locked" in facts["error"], facts["error"]
    assert len(facts["attempts"]) == 1, (
        f"with no wait budget there must be no second attempt, "
        f"attempts at {facts['attempts']} s"
    )


def test_L1_an_error_that_is_not_a_lock_is_raised_at_once(tmp_path):
    """A damaged file must not be retried for a minute before it fails."""
    facts = _init_db_child(L1_OTHER_ERROR, tmp_path / "ioerror.db", None,
                           "disk-I/O-error child")

    assert facts["outcome"] == "sqlalchemy.exc.OperationalError", facts
    assert "disk I/O error" in facts["error"], facts["error"]
    assert facts["attempts"] == [1], (
        f"an OperationalError without 'locked' must not be retried, "
        f"attempts={facts['attempts']}"
    )
    assert facts["elapsed"] < 5.0, (
        f"it must be raised immediately, not after a busy_timeout: {facts['elapsed']} s"
    )



def _sized(path, n):
    with open(path, "wb") as fh:
        fh.truncate(n)


def test_V2_wal_pages_count_towards_the_copy(tmp_path, monkeypatch):
    """Pages still in -wal are copied by the VACUUM too."""
    from sqlalchemy import create_engine
    from workers.cleanup import _has_room_for_vacuum

    db = tmp_path / "wal.db"
    _sized(db, 4096)
    _sized(f"{db}-wal", 10 * 1024 * 1024)
    engine = create_engine(f"sqlite:///{db}")
    free = {"value": 1024 * 1024}
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda _t: DiskUsage(total=10**12, used=0, free=free["value"]))
    assert _has_room_for_vacuum(engine) is False, "-wal size must count"
    free["value"] = 2 * (4096 + 10 * 1024 * 1024)
    assert _has_room_for_vacuum(engine) is True


def test_V2_temp_dir_needs_room_too(tmp_path, monkeypatch):
    """The temporary copy may sit on another filesystem (SQLITE_TMPDIR)."""
    from sqlalchemy import create_engine
    from workers.cleanup import _has_room_for_vacuum

    db = tmp_path / "db" / "t.db"
    db.parent.mkdir()
    _sized(db, 1024 * 1024)
    tmp = tmp_path / "sqlite-tmp"
    tmp.mkdir()
    monkeypatch.setenv("SQLITE_TMPDIR", str(tmp))
    engine = create_engine(f"sqlite:///{db}")

    def disk_usage(target):
        small = os.path.abspath(target) == str(tmp)
        return DiskUsage(total=10**12, used=0, free=1024 if small else 10**9)

    monkeypatch.setattr(shutil, "disk_usage", disk_usage)
    assert _has_room_for_vacuum(engine) is False, "temp dir without room must block the VACUUM"
    monkeypatch.delenv("SQLITE_TMPDIR")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert _has_room_for_vacuum(engine) is True


def test_V3_migration_skips_unique_autoindexes(tmp_path):
    """sqlite_autoindex_* cannot be dropped; the migration must leave them alone."""
    import sqlalchemy as sa
    from app.database import _migrate_tasks_autoincrement
    from app.models.task import Task

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'uniq.db'}")
    md = sa.MetaData()
    sa.Table("api_keys", md, sa.Column("id", sa.Integer, primary_key=True))
    legacy = Task.__table__.to_metadata(md)
    legacy.dialect_options["sqlite"]["autoincrement"] = False
    legacy.append_column(sa.Column("legacy_ref", sa.String(20), unique=True))
    md.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "insert into tasks (id, api_key_id, type, status, input_data, legacy_ref) "
            "values (3, 1, 'image_text', 'solved', '{}', 'a')")
        assert conn.exec_driver_sql(
            "select count(*) from sqlite_master where name like 'sqlite_autoindex_tasks%'"
        ).scalar() == 1
        assert _migrate_tasks_autoincrement(conn) is True
        ddl = conn.exec_driver_sql("select sql from sqlite_master where name='tasks'").scalar()
        assert "AUTOINCREMENT" in ddl.upper()
        assert conn.exec_driver_sql("select id from tasks").scalars().all() == [3]
    engine.dispose()
