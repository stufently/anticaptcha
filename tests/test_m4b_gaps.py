"""Offline regression coverage for the seven M4b mutation survivors."""
import asyncio
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from playwright.async_api import ElementHandle, Error as PlaywrightError, Locator

from app.utils.browser import BrowserManager
from test_m4b_unit import MARKER, PROVIDER, TOKEN, StubClassifier, vision
from workers.classifiers import vision_llm
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
   if (event.data === 'submit') setTimeout(() => window.widgetStats.submits++, STATS_DELAY);
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
 window.frameStats = {submits: 0, refreshes: 0};
 function recordSubmit() {
   window.frameStats.submits++;
   parent.postMessage('submit', '*');
 }
 let round = 0;
 function refresh() {
   round++;
   setTimeout(() => {image.src = 'load-captchaimg?n=' + round}, 200);
 }
 document.querySelector('[data-testid="refresh"]').onclick = () => {
   window.frameStats.refreshes++;
   parent.postMessage('refresh', '*'); refresh();
 };
"""

BODIES = {
    'late-token': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
   setTimeout(() => parent.postMessage('token', '*'), TOKEN_DELAY);
 };
</script>""",
    'hint-then-hide': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
   hint.textContent = 'Попробуйте ещё раз'; hint.style.display = 'block';
   setTimeout(() => parent.postMessage('hide', '*'), 500);
   setTimeout(() => parent.postMessage('token', '*'), TOKEN_DELAY);
 };
</script>""",
    # Submit changes nothing at all: no token, no hint, no new image. The only
    # way out of the outcome window is its own bound.
    'silent': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
 };
</script>""",
    # Rejection is announced by a NEW hint only, the image src stays put.
    'hint-only': HEAD + """
 let rejects = 0;
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
   rejects++;
   hint.textContent = 'Попробуйте ещё раз. Вариант ' + rejects;
   hint.style.display = 'block';
 };
</script>""",
    # First answer wrong (hint + new image), second answer right: the widget
    # clears the stale hint at once and issues the token 1.5 s later.
    'hint-clears': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
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
   recordSubmit();
   parent.postMessage('hide', '*');
   setTimeout(() => parent.postMessage('token', '*'), TOKEN_DELAY);
 };
</script>""",
    # Ordinary challenge, used with an aborted image request.
    'standard': HEAD + """
 document.querySelector('[data-testid="submit"]').onclick = () => {
   recordSubmit();
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
            broken_image=False, configure=None, reuse_solver=None, stats_delay=0):
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
                            '; const TOKEN = ' + json.dumps(TOKEN) +
                            '; const STATS_DELAY = ' + str(stats_delay) + ';' + WIDGET)
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
                    # Counters belong to the handler that performed the action;
                    # its postMessage may still be queued on the main page.
                    frame_stats = [await frame.evaluate('window.frameStats')
                                   for frame in page.frames if frame.url == PROVIDER + 'challenge']
                    if frame_stats:
                        for key in ('submits', 'refreshes'):
                            stats[key] = sum(item[key] for item in frame_stats)
                finally:
                    await close_page(page)

            monkeypatch.setattr(manager, 'new_page', routed_page)
            monkeypatch.setattr(manager, 'close_page', capture_and_close)
            solver = reuse_solver or smartcaptcha.SmartCaptchaSolver()
            solver.vision_classifier = classifier
            if configure is not None:
                configure(solver)
            original_text = solver._solve_text

            async def record_text(page):
                result = await original_text(page)
                stats.setdefault('text_returns', []).append((result, time.monotonic()))
                return result

            monkeypatch.setattr(solver, '_solve_text', record_text)
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
    15s' instead of 'not solved in 1 rounds'.
    """
    classifier = StubClassifier(['ошибка'])
    with pytest.raises(RuntimeError, match='not solved in 1 rounds'):
        fake_yandex(classifier, mode='silent', deadline=15, max_rounds=1)
    elapsed = fake_yandex.stats['elapsed']
    assert 9.0 <= elapsed < 14.0, elapsed
    assert smartcaptcha.OUTCOME_WAIT_SECONDS == 10
    assert len(classifier.calls) == 1
    assert fake_yandex.stats['submits'] == 1


def test_S2_hint_change_alone_is_a_rejection(fake_yandex):
    """Kills OC05 (the hint half of the rejection condition dropped).

    The widget announces the rejection with a new hint and keeps the image, so
    the src check alone never fires. The solver must leave the outcome window
    at once; without the hint condition it burns the whole 10 s window.
    """
    classifier = StubClassifier(['ошибка'])
    with pytest.raises(RuntimeError, match='not solved in 1 rounds'):
        fake_yandex(classifier, mode='hint-only', deadline=15, max_rounds=1, stats_delay=2000)
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
                       deadline=8, max_rounds=2) == {'token': TOKEN}
    assert len(classifier.calls) == 2
    assert classifier.calls[0] != classifier.calls[1]
    assert fake_yandex.stats['submits'] == 2


def test_S4_hidden_iframe_without_token_returns_to_poll(fake_yandex):
    """Kills OC04 (hidden advanced-iframe no longer returns None).

    The iframe hides without a token. _solve_text must immediately return
    None to _poll, before a token appears 1.5 s later. Reading the token from
    inside the outcome loop instead would also solve, but violate handoff.
    """
    classifier = StubClassifier(['ошибка'])
    assert fake_yandex(classifier, mode='hide-no-token', token_delay=1500,
                       deadline=4) == {'token': TOKEN}
    result, returned_at = fake_yandex.stats['text_returns'][0]
    assert result is None
    assert returned_at - fake_yandex.stats['poll_started_at'] < 2
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


def test_late_token_while_waiting_for_new_image(fake_yandex):
    classifier = StubClassifier(['парус'])
    assert fake_yandex(classifier, mode='late-token', token_delay=11000,
                       deadline=14) == {'token': TOKEN}
    assert len(classifier.calls) == 1
    assert fake_yandex.stats['submits'] == 1


def test_hidden_iframe_while_waiting_for_new_image(fake_yandex):
    classifier = StubClassifier(['ошибка'])
    assert fake_yandex(classifier, mode='hint-then-hide', token_delay=1500,
                       deadline=4) == {'token': TOKEN}
    assert fake_yandex.stats['text_returns'][0][0] is None
    assert len(classifier.calls) == 1


def test_iframe_hides_between_browser_roundtrips(fake_yandex, monkeypatch):
    hidden = []

    def configure(solver):
        solve_text = solver._solve_text

        async def run(page):
            def intercept(check):
                async def is_visible(node, **kwargs):
                    visible = await check(node, **kwargs)
                    if (visible and not hidden and
                            await page.evaluate('window.widgetStats.submits === 1') and
                            await node.evaluate('el => el.tagName') == 'IFRAME'):
                        hidden.append(True)
                        await page.evaluate('''token => {
                            document.querySelector('iframe[data-testid="advanced-iframe"]').style.display = 'none';
                            setTimeout(() => document.querySelector('input[name="smart-token"]').value = token, 200);
                        }''', TOKEN)
                    return visible
                return is_visible

            for cls in (Locator, ElementHandle):
                monkeypatch.setattr(cls, 'is_visible', intercept(cls.is_visible))
            return await solve_text(page)

        monkeypatch.setattr(solver, '_solve_text', run)

    assert fake_yandex(StubClassifier(['парус']), mode='silent', deadline=4,
                       configure=configure) == {'token': TOKEN}
    assert hidden


def test_round_budget_survives_playwright_reentry(fake_yandex, monkeypatch):
    screenshot = Locator.screenshot
    shots = []

    async def transient_failure(locator, **kwargs):
        shots.append(locator)
        if len(shots) == 3:
            raise PlaywrightError('frame temporarily replaced')
        return await screenshot(locator, **kwargs)

    monkeypatch.setattr(Locator, 'screenshot', transient_failure)
    classifier = StubClassifier(['ошибка'] * 8)
    with pytest.raises(RuntimeError, match='not solved in 3 rounds'):
        fake_yandex(classifier, deadline=12)
    assert len(shots) == 4, 'the interrupted third screenshot must be retried'
    assert len(classifier.calls) == 3
    assert fake_yandex.stats['submits'] == 3


@pytest.mark.parametrize('stage', ['fill', 'typing', 'submit'])
def test_input_failure_retries_the_unsubmitted_image(fake_yandex, monkeypatch, stage):
    """The last submitted src must survive an error before the next submit."""
    method = {'fill': 'fill', 'typing': 'press_sequentially', 'submit': 'click'}[stage]
    action = getattr(Locator, method)
    attempts = []

    async def fail_second_input(locator, *args, **kwargs):
        if stage == 'submit' and await locator.get_attribute('data-testid') != 'submit':
            return await action(locator, *args, **kwargs)
        attempts.append(await locator.evaluate(
            'el => document.querySelector(".AdvancedCaptcha-View img").src'))
        if len(attempts) == 2:
            if stage == 'typing':
                await action(locator, args[0][:2], **kwargs)
            raise PlaywrightError('one transient input failure')
        return await action(locator, *args, **kwargs)

    monkeypatch.setattr(Locator, method, fail_second_input)
    classifier = StubClassifier(['ошибка', 'парус', 'парус'])
    assert fake_yandex(classifier, deadline=6) == {'token': TOKEN}
    assert len(attempts) == 3
    assert attempts[0] != attempts[1]
    assert attempts[1] == attempts[2]
    assert len(classifier.calls) == 3
    assert classifier.calls[0] != classifier.calls[1]
    # Focusing the field can repaint the screenshot's last row. The src and
    # image interior identify the unchanged challenge across the retry.
    for shot in classifier.calls[1:]:
        with Image.open(io.BytesIO(shot)) as image:
            assert image.size == (248, 81)
            assert image.convert('RGB').getpixel((124, 40)) == (90, 70, 140)
    assert fake_yandex.stats['submits'] == 2
    assert fake_yandex.stats['refreshes'] == 0


def test_failed_refresh_does_not_mark_the_image_processed(fake_yandex, monkeypatch):
    click = Locator.click
    failed = []

    async def fail_refresh(locator, **kwargs):
        if await locator.get_attribute('data-testid') == 'refresh' and not failed:
            failed.append(True)
            raise PlaywrightError('one transient refresh failure')
        return await click(locator, **kwargs)

    monkeypatch.setattr(Locator, 'click', fail_refresh)
    classifier = StubClassifier([ValueError('vision LLM returned no text'), 'парус'])
    assert fake_yandex(classifier, deadline=4) == {'token': TOKEN}
    assert failed
    assert len(classifier.calls) == 2
    assert classifier.calls[0] == classifier.calls[1]
    assert fake_yandex.stats['refreshes'] == 0
    assert fake_yandex.stats['submits'] == 1


def test_round_budget_resets_for_next_solve(fake_yandex):
    solver = smartcaptcha.SmartCaptchaSolver()
    classifier = StubClassifier(['ошибка'] * 3)
    with pytest.raises(RuntimeError, match='not solved in 3 rounds'):
        fake_yandex(classifier, reuse_solver=solver, deadline=8)
    assert len(classifier.calls) == 3
    classifier = StubClassifier(['парус'])
    assert fake_yandex(classifier, reuse_solver=solver, deadline=4) == {'token': TOKEN}
    assert len(classifier.calls) == 1


@pytest.mark.parametrize('kind', ['text', 'silhouette', 'unknown'])
def test_visible_second_advanced_iframe(kind, monkeypatch):
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 3)

    async def run():
        manager = BrowserManager()
        try:
            page = await manager.new_page(stealth=False)
            modifier = {'text': '_image', 'silhouette': '_silhouette'}.get(kind, '')
            await page.set_content('''<input name="smart-token" type="hidden">
                <iframe data-testid="advanced-iframe" style="display:none"
                  srcdoc='<div class="AdvancedCaptcha AdvancedCaptcha_image"></div>'></iframe>
                <iframe data-testid="advanced-iframe"
                  srcdoc='<div class="AdvancedCaptcha AdvancedCaptcha''' + modifier + '''"></div>'></iframe>''')
            solver = smartcaptcha.SmartCaptchaSolver()
            await page.frame_locator('iframe').nth(1).locator('.AdvancedCaptcha').wait_for(state='attached')
            assert await solver._challenge_kind(page) == kind
            if kind == 'text':
                # The text solver must choose the same visible frame too.
                await page.frame_locator('iframe').nth(1).locator('body').evaluate('''body => {
                    body.innerHTML += '<div class="AdvancedCaptcha-View"><img width="248" height="81"></div>' +
                      '<input name="rep"><button data-testid="submit">Submit</button>';
                    const canvas = document.createElement('canvas'); canvas.width=248; canvas.height=81;
                    canvas.getContext('2d').fillRect(0, 0, 248, 81);
                    body.querySelector('img').src = canvas.toDataURL();
                    body.querySelector('button').onclick = () => {
                      parent.document.querySelector('input[name="smart-token"]').value = 'visible-token';
                    };
                }''')
                solver.vision_classifier = StubClassifier(['парус'])
                assert await solver._solve_text(page) == 'visible-token'
        finally:
            await manager.close()

    asyncio.run(run())


def test_disabled_word_in_cli_error_is_retryable(fake_yandex):
    classifier = StubClassifier([RuntimeError('qwen tool disabled temporarily'), 'парус'])
    assert fake_yandex(classifier, deadline=4) == {'token': TOKEN}
    assert fake_yandex.stats['refreshes'] == 1
    assert len(classifier.calls) == 2


def test_disabled_exception_has_own_type(vision):
    vision.enabled = False
    assert issubclass(vision_llm.VisionLLMDisabledError, RuntimeError)
    with pytest.raises(vision_llm.VisionLLMDisabledError,
                       match=r'^Vision LLM is disabled \(no API key\)$'):
        asyncio.run(vision.read_text(b'image'))


def test_concurrent_cli_calls_keep_their_own_schema(vision, monkeypatch):
    paths = []

    async def run():
        both_started = asyncio.Event()

        async def spawn(*argv, **kwargs):
            path = Path(argv[argv.index('--json-schema') + 1][1:])
            paths.append(path)
            if len(paths) == 2:
                both_started.set()
            await both_started.wait()
            schema = json.loads(path.read_text())
            result = {'text': 'парус'} if 'text' in schema['properties'] else {'indices': [0]}

            async def communicate():
                assert path.exists(), 'CLI must keep access to its schema until completion'
                return json.dumps({'type': 'result', 'structured_result': result}).encode(), b''

            return SimpleNamespace(communicate=communicate, returncode=0)

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        return await asyncio.wait_for(asyncio.gather(
            vision.read_text(b'image'), vision.classify_tiles(b'image', 'bicycles')), 3)

    assert asyncio.run(run()) == ['парус', [0]]
    assert len(set(paths)) == 2
    assert all(not path.exists() for path in paths)
    assert list(vision.temp_dir.iterdir()) == []


@pytest.mark.parametrize('cancelled', [False, True])
def test_schema_cleanup_on_error_and_cancellation(vision, monkeypatch, cancelled):
    paths = []
    killed = []

    async def spawn(*argv, **kwargs):
        paths.append(Path(argv[argv.index('--json-schema') + 1][1:]))
        assert paths[-1].exists()
        if not cancelled:
            raise FileNotFoundError('CLI not installed')

        async def communicate():
            raise asyncio.CancelledError

        async def wait():
            pass

        return SimpleNamespace(communicate=communicate, kill=lambda: killed.append(True), wait=wait)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
        asyncio.run(vision.read_text(b'image'))
    assert paths and all(not path.exists() for path in paths)
    assert list(vision.temp_dir.iterdir()) == []
    assert bool(killed) == cancelled
