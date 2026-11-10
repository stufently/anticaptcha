"""ASGI middleware capping the HTTP request body size.

Routes parse JSON before the Bearer token is checked, so without a cap an
anonymous client could make the API buffer an arbitrarily large body.
Content-Length above the limit -> 413 before the body is read; a body without
Content-Length (chunked) is counted while it streams and cut off at the limit.
"""
import json

from starlette.exceptions import HTTPException

from app.config import settings


class _BodyTooLarge(HTTPException):
    """HTTPException so FastAPI's body parser re-raises it as 413 instead of
    wrapping it into a generic 400 "error parsing the body"."""

    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=f"Request body exceeds {limit} bytes")


async def _send_error(send, status: int, detail: str):
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int = None):
        self.app = app
        self._max_bytes = max_bytes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes if self._max_bytes is not None else settings.max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_bytes
        too_large = f"Request body exceeds {limit} bytes"
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    length = int(value)
                except ValueError:
                    await _send_error(send, 400, "Invalid Content-Length")
                    return
                if length > limit:
                    await _send_error(send, 413, too_large)
                    return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge(limit)
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                raise
            await _send_error(send, 413, too_large)
