"""M4b text challenges, entirely offline with real Chromium and stub OCR."""
import asyncio
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from app.utils.browser import BrowserManager
from workers.classifiers import vision_llm
from workers.solvers import smartcaptcha

PROVIDER = "https://smartcaptcha.yandexcloud.net/"
TOKEN = "M4B-TOKEN-" + "x" * 80
MARKER = "секретныймаркермчетыреб"

WIDGET_SCRIPT = """(() => {
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
   if (event.data === 'solved') {
     document.querySelector('input[name="smart-token"]').value = TOKEN;
     document.querySelector('iframe[data-testid="advanced-iframe"]').style.display = 'none';
   }
 });
})();"""

CHALLENGE = """<!doctype html><meta charset="utf-8">
<div class="AdvancedCaptcha AdvancedCaptcha_image">
 <div class="AdvancedCaptcha-View"><img src="load-captchaimg?n=0" width="248" height="81"></div>
 <input name="rep"><button data-testid="submit">Submit</button>
 <button data-testid="refresh">Refresh</button>
 <div class="Textinput-Hint" style="display:none"></div>
</div><script>
 let round = 0;
 const image = document.querySelector('img');
 const hint = document.querySelector('.Textinput-Hint');
 function refresh() {
   round++;
   // A rejection hint precedes the new image: the next round must wait.
   setTimeout(() => {image.src = 'load-captchaimg?n=' + round}, 200);
 }
 document.querySelector('[data-testid="refresh"]').onclick = () => {
   parent.postMessage('refresh', '*'); refresh();
 };
 document.querySelector('[data-testid="submit"]').onclick = () => {
   parent.postMessage('submit', '*');
   if (document.querySelector('[name="rep"]').value === EXPECTED[round]) {
     setTimeout(() => parent.postMessage('solved', '*'), SUCCESS_DELAY);
   } else {
     hint.textContent = 'Попробуйте ещё раз. Дополнительная проверка';
     hint.style.display = 'block'; refresh();
   }
 };
</script>"""


class StubClassifier:
    enabled = True

    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = []
        self.started_at = None
        self.cancelled = False

    async def read_text(self, image_bytes):
        self.calls.append(image_bytes)
        self.started_at = time.monotonic()
        result = next(self.answers)
        if isinstance(result, Exception):
            raise result
        if result is None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return result


@pytest.fixture
def widget(monkeypatch):
    def run(classifier, expected, *, success_delay=0, kind="text", no_setup=False):
        stats = {}

        async def scenario():
            manager = BrowserManager()
            monkeypatch.setattr(smartcaptcha, 'browser_manager', manager)
            monkeypatch.setattr(smartcaptcha, 'validate_page_url', lambda url: url)

            async def provider(route):
                url = urlsplit(route.request.url)
                if url.path == '/captcha.js':
                    body = ('const PROVIDER = ' + json.dumps(PROVIDER) +
                            '; const TOKEN = ' + json.dumps(TOKEN) + ';' + WIDGET_SCRIPT)
                    await route.fulfill(content_type='application/javascript', body=body)
                elif url.path == '/load-captchaimg':
                    n = int(parse_qs(url.query)['n'][0])
                    output = io.BytesIO()
                    Image.new('RGB', (248, 81), (30 + n * 60, 70, 140)).save(output, format='PNG')
                    await route.fulfill(content_type='image/png', body=output.getvalue())
                elif url.path == '/checkbox':
                    await route.fulfill(content_type='text/html', body='''
                        <button id="js-button" onclick="parent.postMessage('clicked','*')">Check</button>''')
                else:
                    body = ('<script>const EXPECTED = ' + json.dumps(expected) +
                            '; const SUCCESS_DELAY = ' + str(success_delay) + ';</script>' + CHALLENGE)
                    if kind == 'silhouette':
                        body = '<div class="AdvancedCaptcha AdvancedCaptcha_silhouette">Challenge</div>'
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
            if no_setup:
                assert solver.vision_classifier is None
                monkeypatch.setattr(smartcaptcha, 'VisionLLMClassifier', lambda: classifier)
            else:
                solver.vision_classifier = classifier
            original_poll = solver._poll

            async def timed_poll(page):
                stats['poll_started_at'] = time.monotonic()
                return await original_poll(page)

            monkeypatch.setattr(solver, '_poll', timed_poll)
            try:
                return await solver.solve({'site_key': 'offline-key',
                    'page_url': 'https://example.com/', 'render_mode': 'widget'})
            finally:
                await manager.close()

        # Expose counters even when solve raises.
        run.stats = stats
        return asyncio.run(scenario())

    return run


def test_T1_first_round(widget, capfd):
    answer = 'ответ ' + MARKER
    classifier = StubClassifier([answer])
    assert widget(classifier, [answer]) == {'token': TOKEN}
    assert len(classifier.calls) == 1
    assert classifier.calls[0].startswith(b'\x89PNG')
    with Image.open(io.BytesIO(classifier.calls[0])) as shot:
        assert shot.size == (248, 81)
        assert shot.convert('RGB').getextrema() == ((30, 30), (70, 70), (140, 140))
    captured = capfd.readouterr()
    assert MARKER not in captured.out + captured.err
    assert answer not in captured.out + captured.err


def test_T2_retry(widget):
    classifier = StubClassifier(['ошибка', 'парус'])
    assert widget(classifier, ['парус', 'парус'], success_delay=1500) == {'token': TOKEN}
    assert len(classifier.calls) == 2
    assert classifier.calls[0] != classifier.calls[1]
    assert widget.stats['submits'] == 2


def test_T3_exhausted(widget):
    classifier = StubClassifier(['ошибка'] * 3)
    with pytest.raises(RuntimeError, match='not solved in 3 rounds'):
        widget(classifier, ['парус'] * 3)
    assert len(classifier.calls) == 3
    assert widget.stats['submits'] == 3


def test_T4_normalize(widget):
    assert widget(StubClassifier(['  ПРИВЕТ   Мир ']), ['привет мир']) == {'token': TOKEN}


@pytest.mark.parametrize('enabled', [True, False])
def test_T5_llm_disabled(widget, enabled):
    classifier = StubClassifier([vision_llm.VisionLLMDisabledError('Vision LLM is disabled (no API key)')])
    classifier.enabled = enabled
    with pytest.raises(RuntimeError, match='needs the vision LLM'):
        widget(classifier, ['парус'])
    assert widget.stats['submits'] == 0
    assert len(classifier.calls) == int(enabled)


@pytest.mark.parametrize('error', [ValueError('vision LLM returned no text'),
                                  RuntimeError('temporary failure'), asyncio.TimeoutError()])
def test_T5b_llm_glitch(widget, error):
    classifier = StubClassifier([error, 'парус'])
    assert widget(classifier, ['парус'] * 2) == {'token': TOKEN}
    assert widget.stats['refreshes'] == 1
    assert len(classifier.calls) == 2
    assert classifier.calls[0] != classifier.calls[1]


def test_T5c_no_setup(widget):
    classifier = StubClassifier(['парус'])
    assert widget(classifier, ['парус'], no_setup=True) == {'token': TOKEN}
    assert len(classifier.calls) == 1


def test_T6_silhouette_unchanged(widget):
    classifier = StubClassifier([])
    with pytest.raises(RuntimeError, match='silhouette challenge is not supported yet'):
        widget(classifier, [], kind='silhouette')
    assert classifier.calls == []


@pytest.fixture
def vision(tmp_path):
    classifier = object.__new__(vision_llm.VisionLLMClassifier)
    classifier.temp_dir = tmp_path
    classifier.enabled = True
    classifier.vision_model = 'offline-model'
    return classifier


@pytest.mark.parametrize('response, expected', [('{"text": " Парус  "}', 'Парус'),
    ('{}', None), ('{"text": ""}', None), ('{"text": 5}', None),
    ('{"text": "  "}', None), ('[]', None)])
def test_T7_read_text(vision, response, expected, monkeypatch, capfd):
    paths = []

    async def call(image_path, prompt, schema=None):
        paths.append(image_path)
        assert image_path.read_bytes() == b'image'
        assert prompt == vision_llm.TEXT_PROMPT
        assert schema == {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 80}},
                          'required': ['text']}
        return response

    monkeypatch.setattr(vision, '_call_qwen_cli', call)
    if expected is None:
        with pytest.raises(ValueError, match='vision LLM returned no text'):
            asyncio.run(vision.read_text(b'image'))
    else:
        assert asyncio.run(vision.read_text(b'image')) == expected
    assert paths and all(not path.exists() for path in paths)
    captured = capfd.readouterr()
    assert 'Парус' not in captured.out + captured.err


def test_read_text_disabled_and_cleanup(vision, monkeypatch):
    vision.enabled = False
    with pytest.raises(RuntimeError, match=r'^Vision LLM is disabled \(no API key\)$'):
        asyncio.run(vision.read_text(b'image'))
    assert list(vision.temp_dir.iterdir()) == []
    vision.enabled = True
    paths = []

    async def fail(image_path, prompt, schema=None):
        paths.append(image_path)
        raise RuntimeError('CLI failed')

    monkeypatch.setattr(vision, '_call_qwen_cli', fail)
    with pytest.raises(RuntimeError, match='CLI failed'):
        asyncio.run(vision.read_text(b'image'))
    assert paths and all(not path.exists() for path in paths)


def test_T7b_schema_on_cli(vision, monkeypatch, capfd):
    calls = []

    async def spawn(*argv, **kwargs):
        schema = json.loads(Path(argv[argv.index('--json-schema') + 1][1:]).read_text())
        calls.append((argv, schema, kwargs))
        result = {'text': ' Парус '} if 'text' in schema['properties'] else {'indices': [1, 3]}

        async def communicate():
            return json.dumps({'type': 'result', 'structured_result': result}).encode(), b''

        return SimpleNamespace(communicate=communicate, returncode=0)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    assert asyncio.run(vision.read_text(b'image')) == 'Парус'
    assert asyncio.run(vision.classify_tiles(b'image', 'bicycles')) == [1, 3]
    assert set(calls[0][1]['properties']) == {'text'}
    assert set(calls[1][1]['properties']) == {'indices'}
    for argv, schema, kwargs in calls:
        for flag, value in [('--approval-mode', 'plan'), ('--max-tool-calls', '0'),
                            ('--core-tools', 'structured_output')]:
            assert argv[argv.index(flag) + 1] == value
        assert kwargs['start_new_session'] is True
        assert list(argv[argv.index('--exclude-tools') + 1:argv.index('--max-wall-time')]) == vision_llm.EXCLUDED_TOOLS
    captured = capfd.readouterr()
    assert 'Парус' not in captured.out + captured.err


@pytest.mark.parametrize('assistant_text, expected', [
    ('```json\n{"text": "Парус"}\n```', 'Парус'),
    ('{"text": "Парус"}', 'Парус'),
    ('[1, 2]', None), ('```json\n[1, 2]\n```', None),
])
def test_custom_schema_assistant_fallback(vision, monkeypatch, assistant_text, expected, capfd):
    async def spawn(*args, **kwargs):
        async def communicate():
            return json.dumps({'type': 'assistant', 'message': {'content': [
                {'type': 'text', 'text': assistant_text}]}}).encode(), b''
        return SimpleNamespace(communicate=communicate, returncode=0)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    if expected is None:
        with pytest.raises(ValueError, match='vision LLM returned no text'):
            asyncio.run(vision.read_text(b'image'))
    else:
        assert asyncio.run(vision.read_text(b'image')) == expected
    captured = capfd.readouterr()
    assert 'Парус' not in captured.out + captured.err


def test_T8_deadline(widget, monkeypatch):
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 6)
    classifier = StubClassifier([None])
    with pytest.raises(RuntimeError, match='no token within 6s'):
        widget(classifier, ['парус'])
    elapsed = time.monotonic() - widget.stats['poll_started_at']
    assert classifier.started_at is not None
    assert 6 <= elapsed < 12
    assert classifier.cancelled
