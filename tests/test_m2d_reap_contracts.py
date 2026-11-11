"""Additional _reap contracts; all OS signals are mocked, never sent to PID 0."""
import asyncio
import signal

from workers.classifiers import vision_llm


class Process:
    pid = 4242
    returncode = None

    def __init__(self):
        self.events = []

    def kill(self):
        self.events.append('kill')

    async def wait(self):
        self.events.append('wait')


def test_R02_group_signal_is_unconditional_kill(monkeypatch):
    process = Process()
    signals = []
    monkeypatch.setattr(vision_llm.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    asyncio.run(vision_llm._reap(process))
    assert signals == [(4242, signal.SIGKILL)], 'descendants may ignore SIGTERM'


def test_R03_permission_denied_still_reaps_leader(monkeypatch):
    process = Process()

    def denied(pid, sig):
        raise PermissionError('group signal denied')

    monkeypatch.setattr(vision_llm.os, 'killpg', denied)
    error = None
    try:
        asyncio.run(vision_llm._reap(process))
    except PermissionError as exc:
        error = exc
    assert error is None, 'group permission failure must not bypass leader cleanup'
    assert process.events == ['kill', 'wait']


def test_R04_zero_pid_never_signals_callers_group(monkeypatch):
    process = Process()
    process.pid = 0
    groups = []
    monkeypatch.setattr(vision_llm.os, 'killpg', lambda pid, sig: groups.append(pid))
    asyncio.run(vision_llm._reap(process))
    assert groups == [], 'PGID zero addresses the caller process group'
    assert process.events == ['kill', 'wait']


def test_R05_group_killed_before_leader(monkeypatch):
    process = Process()
    monkeypatch.setattr(vision_llm.os, 'killpg', lambda pid, sig: process.events.append('killpg'))
    asyncio.run(vision_llm._reap(process))
    assert process.events == ['killpg', 'kill', 'wait'], 'group cleanup must precede leader cleanup'


def test_R09_wait_cancelled_before_delayed_pipe_close(monkeypatch):
    monkeypatch.setattr(vision_llm, '_REAP_TIMEOUT', 0.2)
    monkeypatch.setattr(vision_llm.os, 'killpg', lambda pid, sig: None)

    class DelayedPipes(Process):
        async def wait(self):
            try:
                await asyncio.sleep(0.3)
                self.events.append('pipes-closed')
            except asyncio.CancelledError:
                self.events.append('wait-cancelled')
                raise

    process = DelayedPipes()
    asyncio.run(vision_llm._reap(process))
    assert 'wait-cancelled' in process.events, 'wait must stop at the configured budget'
    assert 'pipes-closed' not in process.events
