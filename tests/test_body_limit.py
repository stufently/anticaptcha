"""Request body cap: oversized bodies get 413 before auth/JSON parsing."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

LIMIT = 1024


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "max_body_bytes", LIMIT)
    # no `with`: lifespan (DB init) is not needed, nothing must reach a route
    return TestClient(app)


def test_content_length_over_limit_is_413_without_auth(client):
    r = client.post("/api/v1/task", content=b"x" * (LIMIT + 1),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert str(LIMIT) in r.json()["detail"]


def test_chunked_body_over_limit_is_413_without_auth(client):
    def gen():
        for _ in range(4):
            yield b"y" * (LIMIT // 2)
    r = client.post("/api/v1/task", content=gen(),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_body_under_limit_reaches_auth(client):
    r = client.post("/api/v1/task", json={"type": "image_text", "input_data": {}})
    assert r.status_code == 401


def test_default_limit_is_5_mib():
    from app.config import Settings
    assert Settings().max_body_bytes == 5 * 1024 * 1024


def test_content_length_over_limit_rejected_before_body_is_read():
    """413 comes from the header alone: neither receive() nor the app is called."""
    import asyncio
    from app.body_limit import BodySizeLimitMiddleware

    calls = {"app": 0, "receive": 0}
    sent = []

    async def inner_app(scope, receive, send):
        calls["app"] += 1

    async def receive():
        calls["receive"] += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "method": "POST", "path": "/api/v1/task",
        "headers": [(b"content-length", str(LIMIT + 1).encode())],
    }
    asyncio.run(BodySizeLimitMiddleware(inner_app, max_bytes=LIMIT)(scope, receive, send))
    assert sent[0]["status"] == 413
    assert calls == {"app": 0, "receive": 0}
