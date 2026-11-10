"""task_id is never handed out twice: AUTOINCREMENT plus a serialized init_db().

Every scenario runs in its own subprocess with its own ANTICAPTCHA_DATABASE_PATH,
because app.database builds the engine (and its pragmas) at import time: changing
the path in-process would still talk to the engine that is already imported. The
children print one JSON line of facts and the assertions live here, so a failure
names the reason instead of a child's traceback.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD_TIMEOUT = 180

# A 1.0.x database: tasks without AUTOINCREMENT, rows 1, 2 and 5, ix_tasks_id.
# The legacy table is built from the model itself, so the test follows the real
# column list instead of a copy of it.
LEGACY = textwrap.dedent('''
    import sqlalchemy as sa

    from app.database import engine
    from app.models.task import Task

    md = sa.MetaData()
    sa.Table("api_keys", md, sa.Column("id", sa.Integer, primary_key=True))
    legacy = Task.__table__.to_metadata(md)
    legacy.dialect_options["sqlite"]["autoincrement"] = False
    md.create_all(engine)
    with engine.begin() as conn:
        ddl = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='tasks'").scalar()
        assert "AUTOINCREMENT" not in ddl.upper(), ddl
        for i in (1, 2, 5):
            conn.exec_driver_sql(
                "INSERT INTO tasks (id, api_key_id, type, status, input_data, result) "
                f"VALUES ({i}, 7, 'image_text', 'solved', 'in-{i}', 'out-{i}')")
''')

HELPERS = textwrap.dedent('''
    import json
    from datetime import datetime, timedelta

    import app.models  # noqa: F401  registers every table create_all has to make
    from app.database import engine, init_db


    def query(statement):
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(statement)]


    def scalar(statement):
        with engine.connect() as conn:
            return conn.exec_driver_sql(statement).scalar()


    def ddl():
        return scalar("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'")


    def rows():
        return query("SELECT id, api_key_id, type, status, input_data, result "
                     "FROM tasks ORDER BY id")


    def indexes():
        return sorted(row[0] for row in query(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='tasks' AND sql IS NOT NULL"))


    def tables():
        return sorted(row[0] for row in query(
            "SELECT name FROM sqlite_master WHERE type='table'"))


    def leftovers():
        return [name for name in tables() if name.startswith("tasks") and name != "tasks"]


    def autoincrement():
        return "AUTOINCREMENT" in (ddl() or "").upper()


    def new_task_id():
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO tasks (api_key_id, type, status, input_data) "
                                 "VALUES (7, 'image_text', 'pending', '{}')")
            return conn.exec_driver_sql("SELECT max(id) FROM tasks").scalar()


    def delete_all_tasks():
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM tasks")


    def report(**facts):
        print(json.dumps(facts))
''')

FRESH = textwrap.dedent('''
    init_db()
    first, second = new_task_id(), new_task_id()
    delete_all_tasks()
    report(autoincrement=autoincrement(), first=first, second=second,
           after_purge=new_task_id())
''')

LEGACY_MIGRATION = textwrap.dedent('''
    before = rows()
    init_db()
    facts = dict(autoincrement=autoincrement(), rows=rows(), before=before,
                 index_kept="ix_tasks_id" in indexes(), leftovers=leftovers())
    delete_all_tasks()
    facts["next_id_after_purge"] = new_task_id()
    report(**facts)
''')

IDEMPOTENT = textwrap.dedent('''
    before = rows()
    init_db()
    after_first, ddl_first = rows(), ddl()
    init_db()
    report(rows=rows(), before=before, autoincrement=autoincrement(),
           ddl_unchanged=ddl() == ddl_first, leftovers=leftovers())
''')

PURGE = textwrap.dedent('''
    from workers.cleanup import purge_tasks

    init_db()
    last = None
    for _ in range(3):
        last = new_task_id()
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE tasks SET status='solved', created_at=?",
                             (datetime.utcnow() - timedelta(days=30),))
    purged = purge_tasks(engine, now=datetime.utcnow(), task_retention_days=7)
    report(tasks_deleted=purged["tasks_deleted"], last=last,
           after_purge=new_task_id(), autoincrement=autoincrement())
''')

MIGRATE_RETURN = textwrap.dedent('''
    from app.database import _migrate_tasks_autoincrement


    def migrate():
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            rebuilt = _migrate_tasks_autoincrement(conn)
            conn.commit()
        return rebuilt


    on_legacy, second_time = migrate(), migrate()
    report(on_legacy=on_legacy, second_time=second_time, rows=rows(),
           autoincrement=autoincrement(), leftovers=leftovers())
''')

MIGRATE_WITHOUT_TABLE = textwrap.dedent('''
    from app.database import _migrate_tasks_autoincrement

    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        rebuilt = _migrate_tasks_autoincrement(conn)
        conn.commit()
    report(rebuilt=rebuilt, tables=tables())
''')

AFTER_INIT_DB = textwrap.dedent('''
    report(autoincrement=autoincrement(), ids=[row[0] for row in rows()],
           index_kept="ix_tasks_id" in indexes(), leftovers=leftovers(),
           tables=tables())
''')


def _env(db_path):
    env = dict(os.environ)
    env["ANTICAPTCHA_DATABASE_PATH"] = str(db_path)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{old}" if old else str(REPO_ROOT)
    return env


def _spawn(code, db_path):
    return subprocess.Popen(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=_env(db_path),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _child(code, db_path):
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), env=_env(db_path),
        capture_output=True, text=True, timeout=CHILD_TIMEOUT,
    )


def _assert_ok(proc, what):
    assert proc.returncode == 0, (
        f"{what} failed with rc={proc.returncode}\n"
        f"{(proc.stderr or proc.stdout).strip()[-1500:]}"
    )


def _facts(db_path, code, what):
    """Run one child and return the JSON facts it printed."""
    proc = _child(code, db_path)
    _assert_ok(proc, what)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    assert lines, f"{what} printed no facts:\n{proc.stdout.strip()[-800:]}"
    return json.loads(lines[-1])


def _init_db_together(db_path):
    """Two processes run init_db() on one database, started as close as possible.

    Two is what production has (the API and the worker on a fresh volume); the
    caller repeats it to widen the chance of catching an unserialized start.
    Returns [(returncode, stderr), ...].
    """
    procs = [_spawn(HELPERS + "init_db()\n", db_path) for _ in range(2)]
    results = [proc.communicate(timeout=CHILD_TIMEOUT) for proc in procs]
    return [(proc.returncode, err) for proc, (_, err) in zip(procs, results)]


def _assert_both_succeeded(results, what):
    rcs = [rc for rc, _ in results]
    assert rcs == [0, 0], (
        f"{what}: both init_db() calls must succeed, got rc={rcs}\n"
        + "\n".join(err.strip()[-700:] for _, err in results if err.strip())
    )


def test_fresh_database_never_reuses_ids(tmp_path):
    """A purge that deletes the newest row must not give its id back."""
    facts = _facts(tmp_path / "fresh.db", HELPERS + FRESH, "fresh-database child")

    assert facts["autoincrement"], "a fresh tasks table must have AUTOINCREMENT"
    assert facts["after_purge"] == facts["second"] + 1, (
        f"id reused after every row was deleted: {facts['first']}, "
        f"{facts['second']}, then {facts['after_purge']}"
    )


def test_legacy_database_is_migrated_and_keeps_rows(tmp_path):
    """A 1.0.x tasks table is rebuilt with AUTOINCREMENT, rows and index intact."""
    db_path = tmp_path / "legacy.db"
    _assert_ok(_child(LEGACY, db_path), "legacy database prep")

    facts = _facts(db_path, HELPERS + LEGACY_MIGRATION, "migration child")

    assert facts["autoincrement"], "legacy tasks table was not migrated to AUTOINCREMENT"
    assert facts["rows"] == facts["before"], (
        f"migration changed the rows: {facts['before']} -> {facts['rows']}"
    )
    assert facts["index_kept"], "ix_tasks_id was lost by the migration"
    assert facts["leftovers"] == [], f"the migration left a table behind: {facts['leftovers']}"
    assert facts["next_id_after_purge"] == 6, (
        f"after purging the migrated rows (max id 5) the next id must be 6, "
        f"got {facts['next_id_after_purge']}"
    )


def test_repeated_init_db_keeps_a_migrated_database(tmp_path):
    """init_db() runs on every start of the API and of the worker."""
    db_path = tmp_path / "legacy.db"
    _assert_ok(_child(LEGACY, db_path), "legacy database prep")

    facts = _facts(db_path, HELPERS + IDEMPOTENT, "second init_db() child")

    assert facts["rows"] == facts["before"], (
        f"the second init_db() changed the rows: {facts['before']} -> {facts['rows']}"
    )
    assert facts["autoincrement"], "tasks lost AUTOINCREMENT after a second init_db()"
    assert facts["ddl_unchanged"], "a second init_db() rebuilt the tasks table"
    assert facts["leftovers"] == [], f"leftover table: {facts['leftovers']}"


def test_purge_then_create_does_not_reuse_ids(tmp_path):
    """The reported bug: workers/cleanup.purge_tasks frees the newest id."""
    facts = _facts(tmp_path / "purge.db", HELPERS + PURGE, "purge child")

    assert facts["tasks_deleted"] == 3, f"purge deleted {facts['tasks_deleted']} tasks"
    assert facts["autoincrement"], "tasks table without AUTOINCREMENT"
    assert facts["after_purge"] == facts["last"] + 1, (
        f"purged id reused: last task {facts['last']}, new one {facts['after_purge']}"
    )


def test_migrate_rebuilds_only_a_legacy_table(tmp_path):
    """_migrate_tasks_autoincrement reports what it did and does it once."""
    empty = _facts(tmp_path / "empty.db", HELPERS + MIGRATE_WITHOUT_TABLE,
                   "no-table child")
    assert empty["rebuilt"] is False, "there is no tasks table to rebuild"

    db_path = tmp_path / "legacy.db"
    _assert_ok(_child(LEGACY, db_path), "legacy database prep")
    facts = _facts(db_path, HELPERS + MIGRATE_RETURN, "migrate child")

    assert facts["on_legacy"] is True, "the legacy table was not rebuilt"
    assert facts["second_time"] is False, "a migrated table must not be rebuilt again"
    assert facts["autoincrement"], "tasks table without AUTOINCREMENT after the rebuild"
    assert [row[0] for row in facts["rows"]] == [1, 2, 5], f"rows: {facts['rows']}"
    assert facts["leftovers"] == [], f"leftover table: {facts['leftovers']}"


def test_two_processes_migrate_one_legacy_database(tmp_path):
    """API and worker start together on one volume: one migration, data intact."""
    for round_no in range(2):
        db_path = tmp_path / f"concurrent{round_no}.db"
        _assert_ok(_child(LEGACY, db_path), f"legacy database prep (round {round_no})")

        _assert_both_succeeded(
            _init_db_together(db_path), f"concurrent init_db() (round {round_no})")

        facts = _facts(db_path, HELPERS + AFTER_INIT_DB,
                       f"post-check child (round {round_no})")
        assert facts["autoincrement"], (
            f"round {round_no}: tasks not migrated after concurrent init_db()")
        assert facts["ids"] == [1, 2, 5], f"round {round_no}: rows {facts['ids']}"
        assert facts["index_kept"], f"round {round_no}: ix_tasks_id lost"
        assert facts["leftovers"] == [], (
            f"round {round_no}: a second migration left {facts['leftovers']}")


def test_two_processes_create_tables_on_a_fresh_database(tmp_path):
    """The startup race itself: create_all of the second process must not die."""
    for round_no in range(2):
        db_path = tmp_path / f"fresh{round_no}.db"

        _assert_both_succeeded(
            _init_db_together(db_path), f"concurrent init_db() (round {round_no})")

        facts = _facts(db_path, HELPERS + AFTER_INIT_DB,
                       f"post-check child (round {round_no})")
        assert {"tasks", "api_keys", "users", "stats"} <= set(facts["tables"]), (
            f"round {round_no}: tables {facts['tables']}")
        assert facts["autoincrement"], (
            f"round {round_no}: tasks table without AUTOINCREMENT")
