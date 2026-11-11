"""`_reap` must kill the whole qwen group, also after asyncio reaped the leader.

The CLI is started with `start_new_session=True`, so its PID names its process
group. A descendant that inherited stdout/stderr keeps those pipes open after
the leader exited, so the caller's `communicate()` only returns (or times out)
once asyncio has collected the leader and set `returncode`. Skipping `killpg`
at that point leaves the descendant alive: the group ID still cannot name
anybody else's group while a process in it is alive.
"""
import asyncio
import contextlib
import os
import pathlib
import signal
import time

from workers.classifiers.vision_llm import _reap

WAIT_SECONDS = 5.0
POLL_SECONDS = 0.05
SLEEP_SECONDS = 300
SHORT_SLEEP_SECONDS = 0.2


def proc_state(pid):
    """State letter from /proc/<pid>/stat, or None once the PID is gone."""
    try:
        stat = pathlib.Path("/proc/%d/stat" % pid).read_text(encoding="ascii", errors="replace")
    except FileNotFoundError:
        return None
    # The comm field is parenthesised and may hold spaces, so split from the end.
    return stat.rsplit(")", 1)[1].split()[0]


def is_gone(pid):
    """A descendant killed under PID 1 stays a zombie nobody reaps: that is dead."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return proc_state(pid) == "Z"


def read_pid(path):
    return int(pathlib.Path(path).read_text(encoding="ascii").strip())


async def wait_until(predicate):
    """Poll `predicate` for at most WAIT_SECONDS; the caller asserts the result."""
    deadline = time.monotonic() + WAIT_SECONDS
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(POLL_SECONDS)


def cleanup_descendant(path):
    """Kill the descendant by PID if it is still alive, then drop its zombie."""
    if not pathlib.Path(path).is_file():
        return
    pid = read_pid(path)
    if not is_gone(pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    # The orphan is a child of PID 1 in the container, which is this test
    # process: reaping it here is what frees the PID and empties the group.
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


async def drain(process, path):
    """Teardown: nothing may be left running or holding the pipes open."""
    cleanup_descendant(path)
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.communicate(), timeout=WAIT_SECONDS)


def spawn_leader(pid_file, sleep_seconds):
    """Leader exits at once; the backgrounded sleep keeps the pipes open."""
    return asyncio.create_subprocess_exec(
        "sh",
        "-c",
        'sleep %s & echo $! > "%s"; exit 0' % (sleep_seconds, pid_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


def test_R1_reap_kills_group_after_leader_is_reaped(tmp_path):
    pid_file = tmp_path / "gc.pid"

    async def scenario():
        process = await spawn_leader(pid_file, SLEEP_SECONDS)
        try:
            # `communicate()` is deliberately NOT awaited before this: the
            # descendant holds both pipes for the whole sleep, exactly like a
            # qwen node child does. Only the reaped leader is waited for.
            await wait_until(lambda: process.returncode is not None)
            assert process.returncode is not None, (
                "asyncio must set returncode when the leader exits, "
                "without waiting for the pipes the descendant holds"
            )
            descendant = read_pid(pid_file)
            assert not is_gone(descendant), (
                f"the descendant {descendant} must still be alive before _reap "
                f"(state={proc_state(descendant)})"
            )

            await _reap(process)

            await wait_until(lambda: is_gone(descendant))
            assert is_gone(descendant), (
                f"descendant {descendant} survived _reap (state={proc_state(descendant)}): "
                "the process group was not killed after asyncio reaped the leader"
            )
        finally:
            await drain(process, pid_file)

    asyncio.run(scenario())


def test_R1_reap_on_empty_group_raises_nothing(tmp_path):
    """Leader and descendant are both dead: `killpg` on the empty group is safe."""
    pid_file = tmp_path / "gc.pid"

    async def scenario():
        process = await spawn_leader(pid_file, SHORT_SLEEP_SECONDS)
        try:
            await wait_until(lambda: process.returncode is not None)
            assert process.returncode is not None, "the leader must be reaped first"
            descendant = read_pid(pid_file)
            await wait_until(lambda: is_gone(descendant))
            assert is_gone(descendant), (
                f"the descendant {descendant} must be dead before _reap "
                f"(state={proc_state(descendant)})"
            )
            cleanup_descendant(pid_file)

            await _reap(process)
        finally:
            await drain(process, pid_file)

    asyncio.run(scenario())
