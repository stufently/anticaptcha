"""1.2.1 reliability fixes: bounded Turnstile click, tolerant reap, no model
text in the classifier log."""
import asyncio
import json
import time
from types import SimpleNamespace

from workers.classifiers.vision_llm import VisionLLMClassifier, _reap
from workers.solvers import turnstile

PROVIDER_FRAME = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/x"
OUTER_GUARD = 3.0
SECRET = "SECRET-REASONING-7f3a"


# --- Turnstile click is bounded ------------------------------------------


class _HungClickPage:
    """The container answers, the mouse click never returns."""

    def __init__(self):
        self.frames = [SimpleNamespace(url=PROVIDER_FRAME)]
        self.mouse = SimpleNamespace(click=self._click)
        self.click_cancelled = False

    async def evaluate(self, script, *args):
        return {"x": 10, "y": 900, "width": 300, "height": 65}

    async def _click(self, x, y):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.click_cancelled = True
            raise


def _click_with_deadline(page, deadline_in):
    async def run():
        turnstile._poll_deadline.set(time.monotonic() + deadline_in)
        start = time.monotonic()
        clicked = await asyncio.wait_for(
            turnstile.TurnstileSolver()._click_checkbox(page), OUTER_GUARD
        )
        return clicked, time.monotonic() - start

    return asyncio.run(run())


def test_hung_click_times_out_and_is_not_counted(monkeypatch, capsys):
    monkeypatch.setattr(turnstile, "CLICK_TIMEOUT", 0.2, raising=False)
    page = _HungClickPage()
    clicked, elapsed = _click_with_deadline(page, 30)
    assert clicked is False
    assert elapsed < 1.0
    assert page.click_cancelled
    out = capsys.readouterr().out
    assert "click timed out" in out
    assert "clicked the widget checkbox" not in out


def test_click_timeout_never_outlives_poll_deadline(monkeypatch):
    monkeypatch.setattr(turnstile, "CLICK_TIMEOUT", 60.0, raising=False)
    clicked, elapsed = _click_with_deadline(_HungClickPage(), 0.1)
    assert clicked is False
    # bounded by MIN_EVAL_TIMEOUT once the deadline is (nearly) reached
    assert elapsed < turnstile.MIN_EVAL_TIMEOUT + 0.5


# --- _reap survives PermissionError from kill() ----------------------------


class _ForeignProcess:
    pid = None  # skip killpg: only process.kill() is under test

    def __init__(self):
        self.waited = False

    def kill(self):
        raise PermissionError("not permitted")

    async def wait(self):
        self.waited = True


def test_reap_tolerates_permission_error_and_still_waits():
    process = _ForeignProcess()
    asyncio.run(_reap(process))
    assert process.waited


# --- no model text in the log -----------------------------------------------


class _FakeQwen:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0

    async def communicate(self):
        return self.stdout.encode(), b""

    def kill(self):
        pass

    async def wait(self):
        pass


def _classify(monkeypatch, stdout):
    monkeypatch.setenv("BAILIAN_CODING_PLAN_API_KEY", "test-key")

    async def fake_exec(*cmd, **kwargs):
        return _FakeQwen(stdout)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    classifier = VisionLLMClassifier()
    return asyncio.run(classifier.classify_tiles(b"\x89PNG", "Select all buses"))


def _assistant(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def test_structured_answer_extra_fields_not_logged(monkeypatch, capsys):
    stdout = json.dumps([
        _assistant(f"thinking: {SECRET}"),
        {"type": "result", "structured_result": {"indices": [1, 4], "reasoning": SECRET}},
    ])
    assert _classify(monkeypatch, stdout) == [1, 4]
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "2 tile(s) selected" in out


def test_text_answer_reasoning_not_logged(monkeypatch, capsys):
    stdout = json.dumps([_assistant(f"{SECRET} so the answer is [2, 5]")])
    assert _classify(monkeypatch, stdout) == [2, 5]
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "2 tile(s) selected" in out


def test_markdown_answer_strings_not_logged(monkeypatch, capsys):
    stdout = json.dumps([_assistant(f'```json\n["{SECRET}", 3]\n```')])
    assert _classify(monkeypatch, stdout) == [3]
    assert SECRET not in capsys.readouterr().out


def test_unparsable_answer_not_logged(monkeypatch, capsys):
    stdout = json.dumps([_assistant(f"I cannot tell. {SECRET}")])
    assert _classify(monkeypatch, stdout) == []
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "chars" in out


def test_jsonl_first_line_not_logged(monkeypatch, capsys):
    stdout = "\n".join([
        json.dumps(_assistant(SECRET)),
        json.dumps({"type": "result", "structured_result": {"indices": [0]}}),
    ])
    assert _classify(monkeypatch, stdout) == [0]
    assert SECRET not in capsys.readouterr().out
