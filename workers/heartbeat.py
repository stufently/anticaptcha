"""Worker liveness heartbeat.

The worker touches a small file from its own event loop, and a probe runs
``python -m workers.heartbeat --check --max-age N`` to tell a live worker from
a wedged one: a blocked event loop stops touching the file, so the stamp goes
stale and the pod is restarted.
"""
import argparse
import asyncio
import os
import sys
import tempfile
import time
from typing import List, Optional

from app.config import settings

DEFAULT_MAX_AGE = 30.0


def beat(path: str) -> None:
    """Write the current timestamp to `path` atomically.

    Atomic means a temporary file next to the target plus `os.replace`: a probe
    never reads a half-written stamp, and a crash mid-write leaves the previous
    value, which then simply goes stale.
    """
    target = os.fspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    handle, tmp = tempfile.mkstemp(prefix=".heartbeat-", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as fh:
            fh.write(repr(time.time()))
        os.replace(tmp, target)
    except Exception:
        # Never leave a half-written stamp behind; the caller logs and retries
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_fresh(path: str, max_age: float, now: Optional[float] = None) -> bool:
    """True only when `path` holds a numeric stamp no older than `max_age`."""
    try:
        with open(path, "r", encoding="ascii") as fh:
            stamp = float(fh.read().strip())
    except (OSError, ValueError):
        # Missing, unreadable or not a number: not fresh, never an exception
        return False
    if now is None:
        now = time.time()
    return (now - stamp) <= max_age


async def heartbeat_loop(path: str, interval: float) -> None:
    """Touch the heartbeat file forever, once per `interval` seconds."""
    while True:
        try:
            beat(path)
        except Exception as exc:
            # A read-only or full /tmp must not take the worker down: keep the
            # loop alive and let the probe restart the pod instead.
            print(
                f"⚠️ Heartbeat write failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
        await asyncio.sleep(interval)


def main(argv: Optional[List[str]] = None) -> int:
    """Probe entry point: rc 0 when the heartbeat is fresh, rc 1 otherwise."""
    parser = argparse.ArgumentParser(
        prog="python -m workers.heartbeat",
        description="Check the worker heartbeat file",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="exit 0 if the heartbeat is fresh, 1 otherwise",
    )
    parser.add_argument(
        "--max-age", type=float, default=DEFAULT_MAX_AGE,
        help="maximum accepted age in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--path", default=None,
        help="heartbeat file (default: ANTICAPTCHA_WORKER_HEARTBEAT_FILE)",
    )
    args = parser.parse_args(argv)

    if not args.check:
        print("nothing to do: pass --check", file=sys.stderr)
        return 2

    path = args.path or settings.worker_heartbeat_file
    fresh = is_fresh(path, args.max_age)
    print(
        f"heartbeat {path}: {'fresh' if fresh else 'stale or missing'}"
        f" (max age {args.max_age}s)"
    )
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
