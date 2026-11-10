"""Per-key quota on active tasks in POST /api/v1/task.

Each test gets its own database file and its own engine, injected through
`dependency_overrides`: the app's global engine is bound to whichever
ANTICAPTCHA_DATABASE_PATH was set when app.database was first imported, so
depending on it would make these tests sensitive to collection order.

The HTTP tests deliberately share ONE session between requests, exactly like
tests/test_api.py does, because `create_task` takes the quota lock on the
session's own connection.
"""
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.tasks import create_task
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.api_key import APIKey, User
from app.models.task import Task
from app.schemas.task import TaskCreate

BODY = {"type": "image_text", "input_data": {"image": "aGVsbG8="}}


class Quota:
    """One database of its own plus the helpers the tests need."""

    def __init__(self, engine, session_factory):
        self.engine = engine
        self.Session = session_factory

    def make_key(self, name):
        db = self.Session()
        try:
            user = User(username=name, password_hash="h", password_salt="s")
            db.add(user)
            db.commit()
            raw = APIKey.generate_key()
            key = APIKey(user_id=user.id, key_hash=APIKey.hash_key(raw))
            db.add(key)
            db.commit()
            return raw, key.id
        finally:
            db.close()

    @staticmethod
    def headers(raw):
        return {"Authorization": f"Bearer {raw}"}

    def count(self, key_id, statuses=("pending", "processing")):
        stmt = select(func.count()).select_from(Task).where(Task.api_key_id == key_id)
        if statuses:
            stmt = stmt.where(Task.status.in_(statuses))
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one()

    def set_status(self, task_id, status):
        db = self.Session()
        try:
            db.get(Task, task_id).status = status
            db.commit()
        finally:
            db.close()


@pytest.fixture
def quota(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'quota.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        yield Quota(engine, factory)
    finally:
        engine.dispose()


@pytest.fixture
def client(quota):
    """TestClient whose get_db is this test's session (one session for all
    requests, like tests/test_api.py)."""
    db = quota.Session()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    db.close()


def _post(client, quota, raw):
    return client.post("/api/v1/task", json=BODY, headers=quota.headers(raw))


def test_over_limit_rejected_with_429(client, quota, monkeypatch):
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 2)
    raw, key_id = quota.make_key("limit-2")

    for _ in range(2):
        assert _post(client, quota, raw).status_code == 200
    rejected = _post(client, quota, raw)
    assert rejected.status_code == 429, (
        f"the third active task must be rejected with 429, got {rejected.status_code}: "
        f"{rejected.text}"
    )
    assert rejected.json()["detail"] == "Too many active tasks for this API key: limit is 2"
    assert quota.count(key_id) == 2, "a rejected task must not be queued"

    # The limit is read per request, not captured at import time.
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 3)
    assert _post(client, quota, raw).status_code == 200, (
        "raising the limit must free a slot in the next request"
    )
    assert quota.count(key_id) == 3


def test_processing_task_occupies_a_slot(client, quota, monkeypatch):
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 1)
    raw, key_id = quota.make_key("processing")
    task_id = _post(client, quota, raw).json()["task_id"]
    quota.set_status(task_id, "processing")

    rejected = _post(client, quota, raw)
    assert rejected.status_code == 429, (
        "a task the worker is solving right now must still occupy the slot"
    )
    assert quota.count(key_id, statuses=("processing",)) == 1


def test_solved_and_failed_free_their_slots(client, quota, monkeypatch):
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 1)
    raw, key_id = quota.make_key("release")

    first = _post(client, quota, raw).json()["task_id"]
    assert _post(client, quota, raw).status_code == 429
    quota.set_status(first, "failed")
    second = _post(client, quota, raw)
    assert second.status_code == 200, "a failed task must free its slot"

    quota.set_status(second.json()["task_id"], "solved")
    assert _post(client, quota, raw).status_code == 200, "a solved task must free its slot"
    assert quota.count(key_id) == 1


def test_quota_is_counted_per_key(client, quota, monkeypatch):
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 1)
    raw_a, key_a = quota.make_key("key-a")
    raw_b, key_b = quota.make_key("key-b")

    assert _post(client, quota, raw_a).status_code == 200
    assert _post(client, quota, raw_a).status_code == 429
    assert _post(client, quota, raw_b).status_code == 200, (
        "another API key must keep its own quota"
    )
    assert (quota.count(key_a), quota.count(key_b)) == (1, 1)


def test_zero_limit_means_unlimited(client, quota, monkeypatch):
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 0)
    raw, key_id = quota.make_key("unlimited")

    for _ in range(5):
        response = _post(client, quota, raw)
        assert response.status_code == 200, (
            f"max_active_tasks_per_key=0 must mean no limit, got {response.status_code}: "
            f"{response.text}"
        )
    assert quota.count(key_id) == 5


def test_concurrent_creates_admit_only_one(quota, monkeypatch):
    """Four threads, limit 1, and a sleep after every COUNT: a check-then-insert
    without the write lock reads the old count in all four and inserts four."""
    monkeypatch.setattr(settings, "max_active_tasks_per_key", 1)
    _, key_id = quota.make_key("race")

    def slow(conn, cursor, statement, params, context, executemany):
        if "count(" in statement.lower():
            time.sleep(0.3)

    results = []
    lock = threading.Lock()

    def create():
        db = quota.Session()
        try:
            key = db.get(APIKey, key_id)
            user = db.get(User, key.user_id)
            try:
                create_task(TaskCreate(**BODY), (key, user), db)
                outcome = 200
            except HTTPException as exc:
                outcome = exc.status_code
            except Exception as exc:
                outcome = f"{type(exc).__name__}: {exc}"
        finally:
            db.close()
        with lock:
            results.append(outcome)

    event.listen(quota.engine, "after_cursor_execute", slow)
    try:
        threads = [threading.Thread(target=create) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        event.remove(quota.engine, "after_cursor_execute", slow)

    assert sorted(results, key=str) == [200, 429, 429, 429], (
        f"concurrent creates must be serialised by the quota lock, got {results}"
    )
    assert quota.count(key_id) == 1, "exactly one task may end up queued"
