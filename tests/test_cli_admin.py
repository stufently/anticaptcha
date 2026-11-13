"""CLI user/key administration: delete-user, revoke-key, list-keys.

Every command runs through app.cli.main() against a throwaway SQLite file; the
last test starts `python -m app.cli` for real, so the module wiring and the
BEGIN IMMEDIATE on the production engine (WAL pragmas) are covered too.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.cli as cli
from app.api.auth import create_api_key, get_current_user
from app.api.tasks import create_task, get_api_key_and_user, get_task
from app.schemas.task import TaskCreate
from app.database import Base
from app.models.api_key import APIKey, User
from app.models.task import Task

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cli.db'}",
                           connect_args={"check_same_thread": False, "timeout": 0.5})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(cli, "SessionLocal", factory)
    yield factory
    engine.dispose()


def add_user(db, username, keys=1, task_statuses=(), key_id=None):
    """User with `keys` keys; every key gets one task per status. Returns raw keys.

    key_id forces the id of the first key: the schema has AUTOINCREMENT now, so
    a reused id (a database from before 1.3.1) has to be planted by hand.
    """
    user = User(username=username, password_hash="x" * 64, password_salt="s")
    db.add(user)
    db.flush()
    raw_keys = []
    for _ in range(keys):
        raw = APIKey.generate_key()
        key = APIKey(user_id=user.id, key_hash=APIKey.hash_key(raw),
                     id=key_id if not raw_keys else None)
        db.add(key)
        db.flush()
        for status in task_statuses:
            db.add(Task(api_key_id=key.id, type="image_text", status=status,
                        input_data="{}"))
        raw_keys.append(raw)
    db.commit()
    return raw_keys


def run_cli(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["app.cli", *argv])
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


def counts(factory, username):
    db = factory()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            return None
        key_ids = [k.id for k in db.query(APIKey).filter(APIKey.user_id == user.id)]
        tasks = db.query(Task).filter(Task.api_key_id.in_(key_ids)).count()
        return len(key_ids), tasks
    finally:
        db.close()


def orphan_tasks(factory):
    db = factory()
    try:
        return db.execute(Base.metadata.tables["tasks"].select().where(
            ~Base.metadata.tables["tasks"].c.api_key_id.in_(
                db.query(APIKey.id).scalar_subquery()))).fetchall()
    finally:
        db.close()


def authenticate(factory, raw_key):
    db = factory()
    try:
        return get_current_user(authorization=f"Bearer {raw_key}", db=db)
    finally:
        db.close()


# --- delete-user -----------------------------------------------------------

def test_delete_user_without_yes_is_refused_and_deletes_nothing(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    add_user(db, "alice", keys=2, task_statuses=("solved",))
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "delete-user", "alice")

    assert code == 1
    assert "--yes" in err
    assert "deleted" not in out
    assert counts(session_factory, "alice") == (2, 2)


def test_delete_user_unknown_user_fails(session_factory, monkeypatch, capsys):
    db = session_factory()
    add_user(db, "alice")
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "delete-user", "nobody", "--yes")

    assert code == 1
    assert "'nobody' not found" in err
    assert counts(session_factory, "alice") == (1, 0)


def test_delete_user_cascades_keys_and_tasks_only_for_that_user(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    add_user(db, "alice", keys=2, task_statuses=("solved", "failed"))
    bob_keys = add_user(db, "bob", keys=1, task_statuses=("solved",))
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")

    assert code == 0, err
    assert "User 'alice' deleted with 2 API key(s) and 4 task(s)" in out
    assert counts(session_factory, "alice") is None
    db = session_factory()
    try:
        # Not one key row of alice survives, and no task points at a missing key
        assert db.query(APIKey).count() == 1
        assert db.query(Task).count() == 1
    finally:
        db.close()
    assert orphan_tasks(session_factory) == []
    assert counts(session_factory, "bob") == (1, 1)
    assert authenticate(session_factory, bob_keys[0]).username == "bob"


def test_delete_user_with_active_task_is_refused(session_factory, monkeypatch, capsys):
    db = session_factory()
    add_user(db, "alice", keys=1, task_statuses=("solved", "processing"))
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")

    assert code == 1
    assert "1 pending/processing task(s)" in err
    assert counts(session_factory, "alice") == (1, 2)


def test_deleted_users_key_no_longer_authenticates(session_factory, monkeypatch, capsys):
    db = session_factory()
    raw = add_user(db, "alice")[0]
    db.close()
    assert authenticate(session_factory, raw).username == "alice"

    code, _, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")

    assert code == 0, err
    with pytest.raises(HTTPException) as exc:
        authenticate(session_factory, raw)
    assert exc.value.status_code == 401


# --- revoke-key ------------------------------------------------------------

def test_revoke_key_by_id_disables_only_that_key(session_factory, monkeypatch, capsys):
    db = session_factory()
    raw = add_user(db, "alice", keys=2, task_statuses=("solved",))
    first, second = db.query(APIKey).order_by(APIKey.id).all()
    first_id = first.id
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "revoke-key", "--id", str(first_id))

    assert code == 0, err
    assert f"API key id={first_id} revoked" in out
    with pytest.raises(HTTPException) as exc:
        authenticate(session_factory, raw[0])
    assert exc.value.status_code == 401
    assert authenticate(session_factory, raw[1]).username == "alice"
    # Revocation keeps the rows: the task history stays attached to the key
    assert counts(session_factory, "alice") == (2, 2)

    code, out, _ = run_cli(monkeypatch, capsys, "revoke-key", "--id", str(first_id))
    assert code == 0
    assert "already revoked" in out


def test_revoke_key_unknown_id_fails(session_factory, monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, "revoke-key", "--id", "999")

    assert code == 1
    assert "id=999 not found" in err


def test_revoke_key_by_user_disables_all_keys_of_that_user(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    alice = add_user(db, "alice", keys=2)
    bob = add_user(db, "bob", keys=1)
    db.close()

    code, out, err = run_cli(monkeypatch, capsys, "revoke-key", "--user", "alice")

    assert code == 0, err
    assert "Revoked 2 API key(s) of user 'alice'" in out
    for raw in alice:
        with pytest.raises(HTTPException):
            authenticate(session_factory, raw)
    assert authenticate(session_factory, bob[0]).username == "bob"


def test_revoke_key_by_unknown_user_fails(session_factory, monkeypatch, capsys):
    code, _, err = run_cli(monkeypatch, capsys, "revoke-key", "--user", "nobody")

    assert code == 1
    assert "'nobody' not found" in err


@pytest.mark.parametrize("argv", [
    ["revoke-key"],
    ["revoke-key", "--id", "1", "--user", "alice"],
])
def test_revoke_key_needs_exactly_one_target(session_factory, monkeypatch, capsys, argv):
    code, _, _ = run_cli(monkeypatch, capsys, *argv)
    assert code == 2


# --- list-keys and secrecy -------------------------------------------------

def test_list_keys_shows_ids_and_state_but_never_key_material(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    raw = add_user(db, "alice", keys=2)
    keys = db.query(APIKey).order_by(APIKey.id).all()
    ids = [k.id for k in keys]
    hashes = [k.key_hash for k in keys]
    db.close()
    run_cli(monkeypatch, capsys, "revoke-key", "--id", str(ids[0]))

    outputs = []
    code, out, err = run_cli(monkeypatch, capsys, "list-keys", "alice")
    outputs += [out, err]
    assert code == 0, err
    assert f"id={ids[0]} revoked" in out
    assert f"id={ids[1]} active" in out

    for argv in (["revoke-key", "--user", "alice"], ["delete-user", "alice", "--yes"]):
        _, out, err = run_cli(monkeypatch, capsys, *argv)
        outputs += [out, err]
    joined = "\n".join(outputs)
    for secret in raw + hashes:
        assert secret not in joined


def test_list_keys_unknown_user_fails(session_factory, monkeypatch, capsys):
    code, _, err = run_cli(monkeypatch, capsys, "list-keys", "nobody")
    assert code == 1
    assert "'nobody' not found" in err


# --- requests authenticated just before a delete/revoke ------------------

BODY = {"type": "recaptcha_v2",
        "input_data": {"site_key": "k", "page_url": "https://example.com"}}


def stale_auth(factory, raw_key):
    """(api_key, user) as get_api_key_and_user returned it before the CLI ran"""
    db = factory()
    try:
        return get_api_key_and_user(authorization=f"Bearer {raw_key}", db=db)
    finally:
        db.close()


@pytest.mark.parametrize("argv", [
    ["delete-user", "alice", "--yes"],
    ["revoke-key", "--user", "alice"],
])
def test_create_task_rechecks_the_key_under_the_write_lock(
        session_factory, monkeypatch, capsys, argv):
    db = session_factory()
    raw = add_user(db, "alice")[0]
    db.close()
    auth = stale_auth(session_factory, raw)

    code, _, err = run_cli(monkeypatch, capsys, *argv)
    assert code == 0, err

    db = session_factory()
    try:
        with pytest.raises(HTTPException) as exc:
            create_task(TaskCreate(**BODY), auth, db)
        assert exc.value.status_code == 401
        assert db.query(Task).count() == 0
    finally:
        db.close()
    assert orphan_tasks(session_factory) == []


def test_create_task_does_not_follow_a_reused_key_id(session_factory, monkeypatch, capsys):
    db = session_factory()
    alice_raw = add_user(db, "alice")[0]
    db.close()
    alice_auth = stale_auth(session_factory, alice_raw)
    code, _, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")
    assert code == 0, err

    db = session_factory()
    add_user(db, "carol", key_id=alice_auth[0].id)
    try:
        assert db.query(APIKey).one().id == alice_auth[0].id
        with pytest.raises(HTTPException) as exc:
            create_task(TaskCreate(**BODY), alice_auth, db)
        assert exc.value.status_code == 401
        assert db.query(Task).count() == 0
    finally:
        db.close()


def test_create_api_key_for_a_user_deleted_after_auth_is_refused(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    raw = add_user(db, "alice")[0]
    db.close()
    current_user = authenticate(session_factory, raw)
    code, _, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")
    assert code == 0, err

    db = session_factory()
    try:
        with pytest.raises(HTTPException) as exc:
            create_api_key(current_user.id, current_user, db, authorization=f"Bearer {raw}")
        assert exc.value.status_code == 401
        assert db.query(APIKey).count() == 0
    finally:
        db.close()


def test_delete_user_racing_create_api_key_leaves_no_orphan_key(
        session_factory, monkeypatch, capsys):
    """delete-user fires between the user lookup and the insert of the key."""
    from sqlalchemy.exc import OperationalError

    db = session_factory()
    raw = add_user(db, "alice")[0]
    db.close()
    current_user = authenticate(session_factory, raw)
    real_generate = APIKey.generate_key
    outcome = {}

    def generate_while_deleting():
        try:
            cli.delete_user("alice", yes=True)
            outcome["delete"] = "done"
        except OperationalError:
            outcome["delete"] = "locked"
        return real_generate()

    monkeypatch.setattr(APIKey, "generate_key", staticmethod(generate_while_deleting))
    db = session_factory()
    try:
        try:
            create_api_key(current_user.id, current_user, db, authorization=f"Bearer {raw}")
        except HTTPException:
            pass
    finally:
        db.close()

    # The request holds the write lock, so the delete has to wait, not win
    assert outcome["delete"] == "locked"
    db = session_factory()
    try:
        users = {u.id for u in db.query(User)}
        assert all(k.user_id in users for k in db.query(APIKey))
        assert db.query(APIKey).count() == 2
    finally:
        db.close()


def test_delete_user_racing_cli_create_key_leaves_no_orphan_key(
        session_factory, monkeypatch, capsys):
    """Same race through `app.cli create-key`."""
    from sqlalchemy.exc import OperationalError

    db = session_factory()
    add_user(db, "alice")
    db.close()
    real_generate = APIKey.generate_key
    outcome = {}

    def generate_while_deleting():
        try:
            cli.delete_user("alice", yes=True)
            outcome["delete"] = "done"
        except OperationalError:
            outcome["delete"] = "locked"
        return real_generate()

    monkeypatch.setattr(APIKey, "generate_key", staticmethod(generate_while_deleting))
    code, out, err = run_cli(monkeypatch, capsys, "create-key", "alice")

    assert outcome["delete"] == "locked"
    assert code == 0, err
    db = session_factory()
    try:
        users = {u.id for u in db.query(User)}
        assert all(k.user_id in users for k in db.query(APIKey))
        assert db.query(APIKey).count() == 2
    finally:
        db.close()


def test_create_api_key_rechecks_the_callers_key_under_the_lock(
        session_factory, monkeypatch, capsys):
    """revoke-key --user lands between authentication and the insert."""
    db = session_factory()
    raw = add_user(db, "alice")[0]
    db.close()
    current_user = authenticate(session_factory, raw)
    code, _, err = run_cli(monkeypatch, capsys, "revoke-key", "--user", "alice")
    assert code == 0, err

    db = session_factory()
    try:
        with pytest.raises(HTTPException) as exc:
            create_api_key(current_user.id, current_user, db,
                           authorization=f"Bearer {raw}")
        assert exc.value.status_code == 401
        assert db.query(APIKey).filter(APIKey.is_active == True).count() == 0  # noqa: E712
        assert db.query(APIKey).count() == 1
    finally:
        db.close()


def test_get_task_does_not_follow_a_reused_key_id(session_factory, monkeypatch, capsys):
    db = session_factory()
    alice_raw = add_user(db, "alice")[0]
    db.close()
    alice_auth = stale_auth(session_factory, alice_raw)
    code, _, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")
    assert code == 0, err

    db = session_factory()
    add_user(db, "carol", task_statuses=("solved",), key_id=alice_auth[0].id)
    carol_key = db.query(APIKey).one()
    assert carol_key.id == alice_auth[0].id
    task_id = db.query(Task).one().id
    try:
        with pytest.raises(HTTPException) as exc:
            get_task(task_id, alice_auth, db)
        assert exc.value.status_code == 404
        carol_auth = (carol_key, carol_key.user)
        assert get_task(task_id, carol_auth, db).task_id == task_id
    finally:
        db.close()


def test_ids_of_a_deleted_user_and_key_are_never_reused(
        session_factory, monkeypatch, capsys):
    db = session_factory()
    add_user(db, "alice")
    old_user_id = db.query(User).one().id
    old_key_id = db.query(APIKey).one().id
    db.close()
    code, _, err = run_cli(monkeypatch, capsys, "delete-user", "alice", "--yes")
    assert code == 0, err

    db = session_factory()
    try:
        add_user(db, "carol")
        assert db.query(User).one().id > old_user_id
        assert db.query(APIKey).one().id > old_key_id
    finally:
        db.close()


LEGACY_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(64) NOT NULL, is_active BOOLEAN, created_at DATETIME);
CREATE INDEX ix_users_id ON users (id);
CREATE TABLE api_keys (id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id),
    key_hash VARCHAR(64) NOT NULL UNIQUE, is_active BOOLEAN, created_at DATETIME);
CREATE INDEX ix_api_keys_id ON api_keys (id);
INSERT INTO users VALUES (1, 'a', 'h', 1, NULL), (3, 'b', 'h', 1, NULL);
INSERT INTO api_keys VALUES (2, 1, 'k2', 1, NULL), (5, 3, 'k5', 0, NULL);
"""

LEGACY_MIGRATION = """
import json, sqlite3, sys
raw = sqlite3.connect(sys.argv[1])
raw.executescript(sys.argv[2])
raw.commit()
raw.close()

from app.database import engine, init_db
init_db()
with engine.connect() as conn:
    q = lambda sql: [list(r) for r in conn.exec_driver_sql(sql)]
    ddl = dict(q("SELECT name, sql FROM sqlite_master WHERE type='table'"))
    autoinc = {t: "AUTOINCREMENT" in (ddl.get(t) or "").upper()
               for t in ("users", "api_keys", "tasks")}
    rows = dict(users=q("SELECT id, username, is_active, password_salt, is_admin "
                        "FROM users ORDER BY id"),
                keys=q("SELECT id, user_id, key_hash, is_active FROM api_keys ORDER BY id"))
    conn.exec_driver_sql("DELETE FROM api_keys WHERE id=5")
    conn.exec_driver_sql("DELETE FROM users WHERE id=3")
    conn.exec_driver_sql("INSERT INTO users (username, password_hash) VALUES ('c', 'h')")
    conn.exec_driver_sql("INSERT INTO api_keys (user_id, key_hash) VALUES (1, 'k9')")
    facts = dict(
        rows=rows,
        new_user=q("SELECT max(id) FROM users")[0][0],
        new_key=q("SELECT max(id) FROM api_keys")[0][0],
        autoinc=autoinc, tasks_ddl=ddl["tasks"], api_keys_ddl=ddl["api_keys"],
        tables=sorted(ddl), fk_check=q("PRAGMA foreign_key_check"),
    )
    conn.rollback()
print(json.dumps(facts))
"""


def test_init_db_migrates_users_and_api_keys_to_autoincrement(tmp_path):
    import json

    db_path = tmp_path / "legacy.db"
    env = {**os.environ, "ANTICAPTCHA_DATABASE_PATH": str(db_path)}
    proc = subprocess.run(
        [sys.executable, "-c", LEGACY_MIGRATION, str(db_path), LEGACY_SCHEMA],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    facts = json.loads(proc.stdout.strip().splitlines()[-1])

    assert facts["autoinc"] == {"users": True, "api_keys": True, "tasks": True}
    assert facts["rows"] == {
        # A users table from before password_salt/is_admin: those come back NULL
        "users": [[1, "a", 1, None, None], [3, "b", 1, None, None]],
        "keys": [[2, 1, "k2", 1], [5, 3, "k5", 0]],
    }
    # The newest user (3) and key (5) were deleted: their ids are not reused
    assert facts["new_user"] == 4
    assert facts["new_key"] == 6
    # The rename must not repoint other tables' REFERENCES at the temp table
    assert "_pre_autoincrement" not in facts["tasks_ddl"]
    assert "_pre_autoincrement" not in facts["api_keys_ddl"]
    assert "REFERENCES api_keys" in facts["tasks_ddl"]
    assert "REFERENCES users" in facts["api_keys_ddl"]
    assert not [t for t in facts["tables"] if t.endswith("_pre_autoincrement")]
    assert facts["fk_check"] == []


# --- the real entry point --------------------------------------------------

def test_python_m_app_cli_delete_user_end_to_end(tmp_path):
    db_path = tmp_path / "real.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    add_user(db, "alice", keys=2, task_statuses=("solved",))
    db.close()
    env = {**os.environ, "ANTICAPTCHA_DATABASE_PATH": str(db_path)}

    def run(*argv):
        return subprocess.run([sys.executable, "-m", "app.cli", *argv], cwd=REPO_ROOT,
                              env=env, capture_output=True, text=True, timeout=60)

    refused = run("delete-user", "alice")
    assert refused.returncode == 1
    assert counts(factory, "alice") == (2, 2)

    done = run("delete-user", "alice", "--yes")
    assert done.returncode == 0, done.stderr
    assert "deleted with 2 API key(s) and 2 task(s)" in done.stdout
    assert counts(factory, "alice") is None
    db = factory()
    try:
        assert db.query(APIKey).count() == 0
        assert db.query(Task).count() == 0
    finally:
        db.close()
    engine.dispose()
