"""Client image limits: bombs are rejected from the header, before any decode."""
import asyncio
import base64
import io
import json
import struct
import zlib

import cv2 as real_cv2
import numpy as np
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import api_key as _api_key_model  # noqa: F401  registers the table
from app.models.task import Task
from workers import task_worker
from workers.solvers import image_text as image_text_module
from workers.solvers.image_text import ImageTextSolver


def png_header(width: int, height: int) -> bytes:
    """PNG with a truthful IHDR and a minimal IDAT.

    Enough for a header-only size check, far too small to decode: this is what
    an image bomb looks like on the wire (~1 KB instead of ~1.2 MB).
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\x00" * (min(width, 64) * 3))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def real_png(width: int, height: int) -> bytes:
    """A genuinely decodable PNG with text-like black/white blocks."""
    image = Image.new("RGB", (width, height), "white")
    pixels = image.load()
    for x in range(width):
        for y in range(height):
            if (x // 3 + y // 3) % 2 == 0:
                pixels[x, y] = (0, 0, 0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bomb(width: int, height: int) -> bytes:
    """A small valid JPEG whose SOF0 frame header declares a huge image."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(buffer, format="JPEG")
    data = buffer.getvalue()
    marker = data.index(b"\xff\xc0")  # SOF0: FF C0 len(2) prec(1) h(2) w(2)
    return (
        data[: marker + 5]
        + struct.pack(">HH", height, width)
        + data[marker + 9:]
    )


class CountingCv2:
    """The real cv2 with a call counter on imdecode."""

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.imdecode_calls = 0

    def imdecode(self, *args, **kwargs):
        self.imdecode_calls += 1
        return self._wrapped.imdecode(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


class FakeReader:
    """Stands in for easyocr.Reader: no model, no OCR."""

    def readtext(self, image):
        return [(None, "TEXT", 0.9)]


def solve_once(image_bytes: bytes):
    """Run one image_text task through TaskWorker.process_task.

    Real solver, real cv2 (counted), fake OCR reader: the task must fail or
    succeed exactly as the size check decides.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    counting = CountingCv2(real_cv2)
    solver = ImageTextSolver()
    solver.reader = FakeReader()
    solver.cv2 = counting
    solver.np = np

    worker = task_worker.TaskWorker()
    worker.solvers = {"image_text": solver}

    task = Task(
        api_key_id=1,
        type="image_text",
        input_data=json.dumps({"image": base64.b64encode(image_bytes).decode()}),
    )
    db.add(task)
    db.commit()

    asyncio.run(worker.process_task(db, task))
    db.refresh(task)
    outcome = (task.status, task.error_message, task.result)
    db.close()
    return outcome, counting


def test_png_bomb_rejected_before_decode():
    (status, error, result), counting = solve_once(png_header(20000, 20000))
    assert status == "failed", "png bomb task must fail"
    assert error.startswith("Image too large:"), "png bomb must be rejected before decode"
    assert counting.imdecode_calls == 0, "png bomb must never reach cv2.imdecode"
    assert result is None, "png bomb must produce no result"


def test_jpeg_bomb_rejected_before_decode():
    (status, error, result), counting = solve_once(jpeg_bomb(20000, 20000))
    assert status == "failed", "jpeg bomb task must fail"
    assert error.startswith("Image too large:"), "jpeg bomb must be rejected before decode"
    assert counting.imdecode_calls == 0, "jpeg bomb must never reach cv2.imdecode"
    assert result is None, "jpeg bomb must produce no result"


def test_pixel_limit_without_side_limit():
    """3000x3000: every side is legal, the pixel count is not."""
    (status, error, _), counting = solve_once(png_header(3000, 3000))
    assert status == "failed", "pixel-heavy image task must fail"
    assert error.startswith("Image too large:"), "pixel limit must reject 3000x3000"
    assert counting.imdecode_calls == 0, "pixel limit must fire before cv2.imdecode"


def test_side_limit_without_pixel_limit():
    """4097x10: 40970 pixels in total, but one side is over the limit."""
    (status, error, _), counting = solve_once(png_header(4097, 10))
    assert status == "failed", "wide image task must fail"
    assert error.startswith("Image too large:"), "side limit must reject 4097x10"
    assert counting.imdecode_calls == 0, "side limit must fire before cv2.imdecode"


def test_limits_configurable(monkeypatch):
    """Limits come from settings at call time, not from literals."""
    monkeypatch.setattr(image_text_module.settings, "max_image_pixels", 100)
    monkeypatch.setattr(image_text_module.settings, "max_image_side", 10)

    (status, error, _), counting = solve_once(real_png(11, 10))
    assert status == "failed", "11x10 task must fail under tightened limits"
    assert error.startswith("Image too large:"), "tightened limits must reject 11x10"
    assert counting.imdecode_calls == 0, "tightened limits must fire before decode"

    (status, error, result), counting = solve_once(real_png(10, 10))
    assert status == "solved", f"10x10 must pass the tightened limits: {error}"
    assert counting.imdecode_calls == 1, "10x10 must be decoded exactly once"
    assert json.loads(result) == {"text": "TEXT"}, "10x10 must reach the OCR reader"


def test_corrupt_header_fails():
    (status, error, _), counting = solve_once(base64.b64decode("aGVsbG8="))
    assert status == "failed", "corrupt image task must fail"
    assert error.startswith("Unsupported or corrupt image"), "corrupt header must be reported as unsupported"
    assert counting.imdecode_calls == 0, "corrupt header must never reach cv2.imdecode"


def test_normal_image_still_decoded():
    (status, error, result), counting = solve_once(real_png(200, 60))
    assert status == "solved", f"a normal image must still be solved: {error}"
    assert counting.imdecode_calls == 1, "a normal image must be decoded exactly once"
    assert json.loads(result) == {"text": "TEXT"}, "a normal image must reach the OCR reader"
