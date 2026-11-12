"""Offline regression coverage for the seven M4b mutation survivors."""
import asyncio
import io
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from app.utils.browser import BrowserManager
from test_m4b_unit import MARKER, PROVIDER, TOKEN, StubClassifier
from workers.solvers import smartcaptcha

# The M4a widget script, plus two messages the suggested scenarios need:
# 'hide' hides the advanced-iframe WITHOUT issuing a token, 'token' issues the
# token without touching the iframe.
WIDGET = """(() => {
 const container = document.querySelector('.smart-captcha');
 container.innerHTML = '<input type="hidden" name="smart-token">';
 window.widgetStats = {submits: 0, refreshes: 0};
 function frame(testid, path) {
   const node = document.createElement('iframe');
   node.dataset.testid = testid; node.src = PROVIDER + path;
   node.width = 420; node.height = 240; container.append(node);
 }
 frame('checkbox-iframe', 'checkbox');
 window.addEventListener('message', event => {
   if (event.origin !== new URL(PROVIDER).origin) return;
   if (event.data === 'clicked') frame('advanced-iframe', 'challenge');
   if (event.data === 'submit') window.widgetStats.submits++;
   if (event.data === 'refresh') window.widgetStats.refreshes++;
   if (event.data === 'hide') {
     document.querySelector('iframe[data-testid="advanced-iframe"]').style.display = 'none';
   }
   if (event.data === 'token') {
     document.querySelector('input[name="smart-token"]').value = TOKEN;
   }
   if (event.data === 'solved') {
     document.querySelector('input[name="smart-token"]').value = TOKEN;
     document.querySelector('iframe[data-testid="advanced-iframe"]').style.display = 'none';
   }
 });
})();"""

HEAD = """<!doctype html><meta charset="utf-8">
<div class="AdvancedCaptcha AdvancedCaptcha_image">
 <div class="AdvancedCaptcha-View"><img src="load-captchaimg?n=0" width="248" height="81"></div>
 <input name="rep"><button data-testid="submit">Submit</button>
 <button data-testid="refresh">Refresh</button>
 <div class="Textinput-Hint" style="display:none"></div>
</div><script>
 const image = document.querySelector('img');
 const hint = document.querySelector('.Textinput-Hint');
 const field = document.querySelector('[name="rep"]');
 let round = 0;
 function refresh() {
   round++;
   setTimeout(() => {image.src = 'load-captchaimg?n=' + round}, 200);
 }
 document.querySelector('[data-testid="refresh"]').onclick = () => {
   parent.postMessage('refresh', '*'); refresh();
 };
"""

BODIES = {
    # Submit changes nothing at all: no token, no hint, no new image. The only
    # way out of the outcome window is its own bound.
    'silent': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
 };
</script>""",
    # Rejection is announced by a NEW hint only, the image src stays put.
    'hint-only': HEAD + """
 let rejects = 0;
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
   rejects++;
   hint.textContent = 'Попробуйте ещё раз. Вариант ' + rejects;
   hint.style.display = 'block';
 };
</script>""",
    # First answer wrong (hint + new image), second answer right: the widget
    # clears the stale hint at once and issues the token 1.5 s later.
    'hint-clears': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
   if (field.value === EXPECTED[round]) {
     hint.textContent = '';
     hint.style.display = 'none';
     setTimeout(() => parent.postMessage('solved', '*'), SUCCESS_DELAY);
   } else {
     hint.textContent = 'Попробуйте ещё раз. Дополнительная проверка';
     hint.style.display = 'block';
     refresh();
   }
 };
</script>""",
    # The iframe disappears without a token; the token lands on the main page
    # long after the outcome window has closed.
    'hide-no-token': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
   parent.postMessage('hide', '*');
   setTimeout(() => parent.postMessage('token', '*'), TOKEN_DELAY);
 };
</script>""",
    # Ordinary challenge, used with an aborted image request.
    'standard': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
   if (field.value === EXPECTED[round]) {
     setTimeout(() => parent.postMessage('solved', '*'), SUCCESS_DELAY);
   } else {
     hint.textContent = 'Попробуйте ещё раз. Дополнительная проверка';
     hint.style.display = 'block';
     refresh();
   }
 };
</script>""",
}


@pytest.fixture
def fake_yandex(monkeypatch):
    def run(classifier, *, mode='standard', expected=('парус', 'парус', 'парус'),
            success_delay=0, token_delay=0, deadline=None, max_rounds=None,
            broken_image=False):
        stats = {}

        async def scenario():
            manager = BrowserManager()
            monkeypatch.setattr(smartcaptcha, 'browser_manager', manager)
            monkeypatch.setattr(smartcaptcha, 'validate_page_url', lambda url: url)
            if deadline is not None:
                monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', deadline)
            if max_rounds is not None:
                monkeypatch.setattr(smartcaptcha, 'MAX_TEXT_ROUNDS', max_rounds)

            async def provider(route):
                url = urlsplit(route.request.url)
                if url.path == '/captcha.js':
                    body = ('const PROVIDER = ' + json.dumps(PROVIDER) +
                            '; const TOKEN = ' + json.dumps(TOKEN) + ';' + WIDGET)
                    await route.fulfill(content_type='application/javascript', body=body)
                elif url.path == '/load-captchaimg':
                    if broken_image:
                        await route.abort()
                        return
                    n = int(parse_qs(url.query)['n'][0])
                    output = io.BytesIO()
                    Image.new('RGB', (248, 81), (30 + n * 60, 70, 140)).save(output, format='PNG')
                    await route.fulfill(content_type='image/png', body=output.getvalue())
                elif url.path == '/checkbox':
                    await route.fulfill(content_type='text/html', body=(
                        '<button id="js-button" onclick="parent.postMessage(\'clicked\',\'*\')">'
                        'Check</button>'))
                else:
                    body = ('<script>const EXPECTED = ' + json.dumps(list(expected)) +
                            '; const SUCCESS_DELAY = ' + str(success_delay) +
                            '; const TOKEN_DELAY = ' + str(token_delay) + ';</script>' +
                            BODIES[mode])
                    await route.fulfill(content_type='text/html', body=body)

            new_page = manager.new_page
            close_page = manager.close_page

            async def routed_page(**kwargs):
                page = await new_page(**kwargs)
                await page.route(PROVIDER + '**', provider)
                return page

            async def capture_and_close(page):
                try:
                    stats.update(await page.evaluate('window.widgetStats'))
                finally:
                    await close_page(page)

            monkeypatch.setattr(manager, 'new_page', routed_page)
            monkeypatch.setattr(manager, 'close_page', capture_and_close)
            solver = smartcaptcha.SmartCaptchaSolver()
            solver.vision_classifier = classifier
            original_poll = solver._poll

            async def timed_poll(page):
                stats['poll_started_at'] = time.monotonic()
                return await original_poll(page)

            monkeypatch.setattr(solver, '_poll', timed_poll)
            try:
                return await solver.solve({'site_key': 'offline-key',
                                           'page_url': 'https://example.com/',
                                           'render_mode': 'widget'})
            finally:
                await manager.close()

        run.stats = stats
        started = time.monotonic()
        try:
            return asyncio.run(scenario())
        finally:
            stats['elapsed'] = time.monotonic() - started

    return run


def test_S1_outcome_window_is_ten_seconds(fake_yandex):
    """Kills OC02 (outcome_deadline 10 s -> 30 s).

    Nothing happens after submit, so the round ends only when the outcome
    window closes. One round must cost ~10 s, not ~30 s: with a 30 s window the
    poll deadline (15 s) fires first and the task dies with 'no token within
    15s' instead of 'not solved in 3 rounds'.
    """
    classifier = StubClassifier(['ошибка'])
    with pytest.raises(RuntimeError, match='not solved in 3 rounds'):
        fake_yandex(classifier, mode='silent', deadline=15, max_rounds=1)
    elapsed = fake_yandex.stats['elapsed']
    assert 5.0 <= elapsed < 14.0, elapsed
    assert len(classifier.calls) == 1
    assert fake_yandex.stats['submits'] == 1


def test_S2_hint_change_alone_is_a_rejection(fake_yandex):
    """Kills OC05 (the hint half of the rejection condition dropped).

    The widget announces the rejection with a new hint and keeps the image, so
    the src check alone never fires. The solver must leave the outcome window
    at once; without the hint condition it burns the whole 10 s window.
    """
    classifier = StubClassifier(['ошибка'])
    with pytest.raises(RuntimeError, match='not solved in 3 rounds'):
        fake_yandex(classifier, mode='hint-only', deadline=15, max_rounds=1)
    elapsed = fake_yandex.stats['elapsed']
    assert elapsed < 5.0, elapsed
    assert fake_yandex.stats['submits'] == 1


def test_S3_hint_that_disappears_is_not_a_rejection(fake_yandex):
    """Kills OC03 (the 'hint is visible' guard dropped).

    Round 0 is rejected, so a hint stays visible. Round 1 is correct: the
    widget clears the hint and issues the token 1.5 s later. A hint that
    DISAPPEARS is not a rejection - the round must keep waiting for the token
    instead of spending a third round on an image that never changes.
    """
    classifier = StubClassifier(['ошибка', 'парус'])
    assert fake_yandex(classifier, mode='hint-clears', success_delay=1500,
                       deadline=8) == {'token': TOKEN}
    assert len(classifier.calls) == 2
    assert classifier.calls[0] != classifier.calls[1]
    assert fake_yandex.stats['submits'] == 2


def test_S4_hidden_iframe_without_token_returns_to_poll(fake_yandex):
    """Kills OC04 (hidden advanced-iframe no longer returns None).

    The iframe hides without a token and the token appears on the main page
    11 s later, i.e. after the outcome window closed. _solve_text must hand
    control back to _poll, which then reads the token; a solver that stays in
    the round loop waits for a visible image inside a hidden iframe until the
    deadline and fails the task.
    """
    classifier = StubClassifier(['ошибка'])
    assert fake_yandex(classifier, mode='hide-no-token', token_delay=11000,
                       deadline=16) == {'token': TOKEN}
    assert len(classifier.calls) == 1
    assert fake_yandex.stats['submits'] == 1


def test_S5_undecoded_image_is_not_a_loaded_image(fake_yandex):
    """Kills IM02 (naturalWidth > 0 -> >= 0).

    The image request is aborted, so the element is complete but nothing was
    decoded (naturalWidth == 0). Such a frame must never be screenshotted and
    sent to the model: the round waits for a real image and the task ends at
    the poll deadline.
    """
    classifier = StubClassifier(['парус'])
    with pytest.raises(RuntimeError, match='no token within 4s'):
        fake_yandex(classifier, mode='standard', deadline=4, broken_image=True)
    assert classifier.calls == []
    assert fake_yandex.stats['submits'] == 0


def test_S6_deadline_during_recognition_does_not_start_another_round(fake_yandex, capfd):
    """Kills LM03 (the deadline check in the read_text error handler dropped).

    read_text hangs and is cancelled by the poll deadline. That cancellation
    must reach _poll as a timeout, not be handled as an ordinary recognition
    failure: without the deadline check the solver logs 'recognition failed'
    and starts refreshing the image for a task that is already over.

    The counters alone do not discriminate - after the deadline every
    _bounded roundtrip is cut at its 0.5 s floor, so the refresh click usually
    never lands. The log line is the observable difference.
    """
    classifier = StubClassifier([None])
    with pytest.raises(RuntimeError, match='no token within 6s'):
        fake_yandex(classifier, mode='standard', deadline=6)
    captured = capfd.readouterr()
    assert 'recognition failed' not in captured.out + captured.err, \
        'a deadline cancellation must not be handled as a recognition failure'
    elapsed = fake_yandex.stats['elapsed']
    assert classifier.started_at is not None
    assert classifier.cancelled
    assert 6 <= elapsed < 12, elapsed
    assert len(classifier.calls) == 1, 'no round may start after the deadline'
    assert fake_yandex.stats.get('refreshes', 0) == 0, 'no refresh after the deadline'


def test_S7_recognition_failure_log_has_no_exception_text(fake_yandex, capfd):
    """Kills LG03 (the exception message appended to the failure log line).

    The exception comes from the classifier, whose message can carry the model
    output. The log line must stay text-free: the marker injected into the
    exception may not reach stdout or stderr.
    """
    classifier = StubClassifier([RuntimeError('qwen said: ' + MARKER), 'парус'])
    assert fake_yandex(classifier, mode='standard') == {'token': TOKEN}
    assert len(classifier.calls) == 2
    captured = capfd.readouterr()
    assert MARKER not in captured.out + captured.err
    assert 'парус' not in captured.out + captured.err
