"""Worker start: it creates missing tables and survives a broken recovery."""
import asyncio
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest
from sqlalchemy.exc import OperationalError

from workers import task_worker


# Stops run() right after the startup steps: no solver is loaded, no polling.
STOP_AFTER_SETUP = textwrap.dedent(
    """
    import asyncio

    from workers import task_worker


    class StopSetup(Exception):
        pass


    async def fake_setup(self):
        raise StopSetup()


    task_worker.TaskWorker.setup_solvers = fake_setup


    async def main():
        worker = task_worker.TaskWorker()
        try:
            await worker.run()
        except StopSetup:
            pass


    asyncio.run(main())
    """
)


def test_run_on_fresh_database_creates_tables(tmp_path):
    """On a fresh volume the API may not have started yet: the worker itself
    must create the tables instead of dying with "no such table: tasks"."""
    db_path = tmp_path / "fresh" / "anticaptcha.db"
    env = {**os.environ, "ANTICAPTCHA_DATABASE_PATH": str(db_path)}

    proc = subprocess.run(
        [sys.executable, "-c", STOP_AFTER_SETUP],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert proc.returncode == 0, (
        "worker must exit 0 on a fresh database, stderr: "
        + proc.stderr.strip()[-400:]
    )
    assert db_path.is_file(), "worker must create the database file"

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "tasks" in tables, f"worker must create the tasks table, got {sorted(tables)}"


def test_recovery_error_does_not_stop_worker(monkeypatch):
    """Recovery is best-effort: a damaged database must not stop the worker."""
    calls = []
    worker = task_worker.TaskWorker()
    monkeypatch.setattr(task_worker, "init_db", lambda: calls.append("init_db"))

    def broken_recovery():
        raise OperationalError(
            "SELECT FROM tasks", {}, Exception("no such table: tasks")
        )

    monkeypatch.setattr(worker, "recover_interrupted_tasks", broken_recovery)

    class Stop(Exception):
        pass

    async def fake_setup():
        calls.append("setup")
        raise Stop()

    monkeypatch.setattr(worker, "setup_solvers", fake_setup)

    try:
        asyncio.run(worker.run())
    except Stop:
        pass  # expected: the fake setup ends run()
    except Exception as exc:
        pytest.fail(
            f"recovery error must not escape run(), got {type(exc).__name__}: {exc}"
        )

    assert calls == ["init_db", "setup"], (
        "worker must reach setup_solvers after a recovery error"
    )


def test_init_db_before_recovery(monkeypatch):
    """Recovery queries the tasks table, so the tables must exist first."""
    calls = []
    worker = task_worker.TaskWorker()
    monkeypatch.setattr(task_worker, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(
        worker, "recover_interrupted_tasks", lambda: calls.append("recover")
    )

    class Stop(Exception):
        pass

    async def fake_setup():
        calls.append("setup")
        raise Stop()

    monkeypatch.setattr(worker, "setup_solvers", fake_setup)

    try:
        asyncio.run(worker.run())
    except Stop:
        pass
    except Exception as exc:
        pytest.fail(f"run() must not raise here, got {type(exc).__name__}: {exc}")

    assert calls == ["init_db", "recover", "setup"], (
        "startup order must be init_db, then recovery, then solvers"
    )
