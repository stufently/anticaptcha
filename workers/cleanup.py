"""Retention cleanup for the tasks table and SQLite space reclaim.

`input_data` holds up to 5 MB of base64 per task and stayed in SQLite forever:
the volume is small and an external backup may copy the database file whole, so
without cleanup the file grows without bound. Finished tasks are trimmed in two
steps - rows past their retention are deleted, older rows lose their input -
and the freed pages are then handed back to the filesystem.

The worker calls `run_cleanup` through `asyncio.to_thread` (see
`TaskWorker.maybe_cleanup`): the migration `VACUUM` is synchronous and, on the
event loop, would stop the heartbeat long enough for the liveness probe to kill
the pod in the middle of it.
"""
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select, update

import app.database
from app.config import settings
from app.models.task import Task

# Only finished tasks are ever touched: pending/processing rows are live work,
# and a task that never finished must not lose the input it is solved from.
FINISHED_STATUSES = ("solved", "failed")


def purge_tasks(
    engine,
    now: Optional[datetime] = None,
    input_retention_hours: Optional[float] = None,
    task_retention_days: Optional[float] = None,
    batch_size: int = 100,
) -> dict:
    """Delete finished tasks past their retention, then blank the inputs of the
    remaining ones.

    Returns `{"inputs_cleared": int, "tasks_deleted": int}`. `now` is naive UTC
    (`datetime.utcnow()`), the same clock `created_at` uses; retention values
    default to the ones in `settings`, read at call time. Every batch touches at
    most `batch_size` rows and commits on its own, so a large backlog is trimmed
    in steps instead of one long write transaction.

    `batch_size` must be at least 1: SQLite reads `LIMIT 0` as "no rows", so a
    zero batch would report a clean database while trimming nothing, and
    `LIMIT -1` means "no limit at all", which puts the whole backlog back into
    the one long transaction the batching exists to avoid.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if now is None:
        now = datetime.utcnow()
    if input_retention_hours is None:
        input_retention_hours = settings.input_retention_hours
    if task_retention_days is None:
        task_retention_days = settings.task_retention_days
    delete_before = now - timedelta(days=task_retention_days)
    input_before = now - timedelta(hours=input_retention_hours)

    # Deleting goes first: rows that disappear must not be blanked on the way
    # out, and the migration VACUUM of reclaim_space must run over a database
    # that is already trimmed (a VACUUM copies every live page).
    tasks_deleted = 0
    while True:
        with engine.begin() as conn:
            stmt = (
                select(Task.id)
                .where(
                    Task.status.in_(FINISHED_STATUSES),
                    Task.created_at < delete_before,
                )
                .limit(batch_size)
            )
            ids = conn.execute(stmt).scalars().all()
            if not ids:
                break
            tasks_deleted += conn.execute(
                delete(Task).where(Task.id.in_(ids))
            ).rowcount

    # An empty input_data is the marker of "input was purged": the API cannot
    # create a task with "" (json.dumps gives at least "{}"), and the worker
    # only parses the input of a task it took from pending.
    inputs_cleared = 0
    while True:
        with engine.begin() as conn:
            stmt = (
                select(Task.id)
                .where(
                    Task.status.in_(FINISHED_STATUSES),
                    Task.created_at < input_before,
                    Task.input_data != "",
                )
                .limit(batch_size)
            )
            ids = conn.execute(stmt).scalars().all()
            if not ids:
                break
            inputs_cleared += conn.execute(
                update(Task).where(Task.id.in_(ids)).values(input_data="")
            ).rowcount

    return {"inputs_cleared": inputs_cleared, "tasks_deleted": tasks_deleted}


def _has_room_for_vacuum(engine) -> bool:
    """True when the volume can hold a second copy of the database.

    The migration VACUUM rebuilds the file page by page through a temporary
    database, so it needs roughly one more copy of the live size next to the
    original. On a small or a full volume it fails halfway through, and because
    the failure leaves `auto_vacuum` at its old value every following cleanup
    round would attempt exactly the same VACUUM again - each time holding the
    write lock while it copies. Skipping the round costs nothing: the database
    keeps working, the next round retries once space appears.
    """
    path = engine.url.database
    if not path or path == ":memory:":
        return True
    size = os.path.getsize(path) if os.path.exists(path) else 0
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(path))).free
    return free >= 2 * size


def reclaim_space(engine) -> None:
    """Give the pages freed by purge_tasks back to the filesystem.

    A database created before auto_vacuum=INCREMENTAL was set on connect is
    migrated once, with a full VACUUM - which is why purging runs first: a
    VACUUM needs free space for a copy of every live page. When the volume
    cannot hold that copy the migration is skipped with a warning instead of
    failing (see `_has_room_for_vacuum`). An INCREMENTAL database is trimmed
    with `incremental_vacuum` instead and never VACUUMed.
    """
    # VACUUM refuses to run inside a transaction, hence AUTOCOMMIT.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        pragma = conn.exec_driver_sql("PRAGMA auto_vacuum")
        auto_vacuum = pragma.fetchone()[0]
        pragma.close()

        if auto_vacuum != 2 and not _has_room_for_vacuum(engine):
            print("⚠️ Not enough free space for the auto_vacuum migration VACUUM; skipped", flush=True)
        elif auto_vacuum != 2:
            conn.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
            conn.exec_driver_sql("VACUUM")
        else:
            # `execute("PRAGMA incremental_vacuum")` frees ONE page per call in
            # CPython's sqlite3 (measured on sqlite 3.46.1, with and without
            # fetchall); executescript runs the statement to completion.
            dbapi_connection = conn.connection.dbapi_connection
            dbapi_connection.executescript("PRAGMA incremental_vacuum;")

        # Without this the -wal file keeps the freed pages and a backup that
        # copies the database file still sees the old size.
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")


def run_cleanup(engine=None) -> dict:
    """One cleanup round: purge, then reclaim - in this order."""
    if engine is None:
        engine = app.database.engine
    report = purge_tasks(engine)
    reclaim_space(engine)
    return report
