"""SQLite setup: WAL + busy_timeout on every connection, all tables created."""
import sqlite3

from sqlalchemy import inspect

from app.database import engine, init_db


def test_every_connection_uses_wal_and_busy_timeout():
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert raw.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_init_db_creates_stats_table():
    init_db()
    assert {"tasks", "api_keys", "users", "stats"} <= set(inspect(engine).get_table_names())
