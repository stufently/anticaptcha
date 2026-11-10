"""Database connection and session management"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
from app.config import settings

# Ensure data directory exists
Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{settings.database_path}"

engine = create_engine(
    DATABASE_URL,
    # timeout: sqlite3 waits for a lock instead of failing at once
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    """API and worker are separate processes writing one SQLite file: WAL lets
    readers and the writer work concurrently, busy_timeout retries on a lock
    instead of raising "database is locked". auto_vacuum lets the cleanup job
    hand freed pages back to the filesystem; it only takes effect on a new
    database when it is set BEFORE journal_mode=WAL (measured on sqlite 3.46.1),
    and an existing database is migrated by workers/cleanup.py::reclaim_space."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    import app.models  # noqa: F401  registers every table, stats included
    # The API and the worker both call init_db() at startup, and on a fresh
    # volume they start at the same moment: without one write transaction the
    # second create_all dies on "table users already exists" (measured). BEGIN
    # IMMEDIATE takes the writer lock up front, so the loser waits and then sees
    # the tables the winner committed. The tasks migration joins the same
    # transaction: half-migrated schema must not survive a crash.
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        Base.metadata.create_all(bind=conn)
        _migrate_tasks_autoincrement(conn)
        conn.commit()


def _migrate_tasks_autoincrement(conn) -> bool:
    """Rebuild `tasks` with AUTOINCREMENT; SQLite cannot add it with ALTER TABLE.

    A 1.0.x database holds `tasks.id` as a plain `INTEGER PRIMARY KEY`, so
    SQLite hands out `max(id) + 1` again after the newest row is deleted by the
    retention purge and a client with an old id reads its own NEW task instead
    of a 404. AUTOINCREMENT keeps the highest id ever used in `sqlite_sequence`,
    and the only way to get it onto an existing table is to recreate the table
    and copy the rows over — the copy itself seeds `sqlite_sequence` with
    `max(id)`. Returns True when the table was rebuilt, False when there is
    nothing to do (no table yet, or it already has AUTOINCREMENT).

    Runs inside the caller's transaction, so any failure leaves the old table
    exactly as it was.
    """
    from app.models.task import Task  # models import Base from this module

    table = Task.__table__
    ddl = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table.name,),
    ).scalar()
    if ddl is None or "AUTOINCREMENT" in ddl.upper():
        return False

    old = f"{table.name}_pre_autoincrement"
    conn.exec_driver_sql(f'ALTER TABLE "{table.name}" RENAME TO "{old}"')
    # The rename moved the indexes onto the temporary table but kept their
    # names, and the new table brings the very same ones (ix_tasks_id): they
    # have to go first or CREATE TABLE fails on a duplicate index name.
    stale = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (old,)
    ).fetchall()
    for (name,) in stale:
        conn.exec_driver_sql(f'DROP INDEX "{name}"')
    table.create(conn)
    columns = ", ".join(f'"{column.name}"' for column in table.columns)
    conn.exec_driver_sql(
        f'INSERT INTO "{table.name}" ({columns}) SELECT {columns} FROM "{old}"'
    )
    conn.exec_driver_sql(f'DROP TABLE "{old}"')
    return True