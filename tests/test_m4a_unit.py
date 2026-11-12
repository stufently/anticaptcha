"""M4a contracts against Chromium and a fully routed, offline provider."""
import asyncio
import json
import socket
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.task import Task
from app.utils.browser import BrowserManager
from workers import task_worker
from workers.solvers import smartcaptcha
from workers.solvers.proxy import parse_proxy

TOKEN = "SMART-TOKEN-" + "x" * 80
PROVIDER = "https://smartcaptcha.yandexcloud.net/"

SCRIPT = """(() => {
 const kind = new URL(location.href).searchParams.get('scenario') || 'checkbox';
 const container = document.querySelector('.smart-captcha');
 container.dataset.testid = 'smartCaptcha-container';
 const input = document.createElement('input');
 input.type = 'hidden'; input.name = 'smart-token'; container.append(input);
 const issue = () => { input.value = TOKEN; };
 window.smartCaptcha = { getResponse: () => input.value,
   execute: () => { if (kind === 'invisible') issue(); } };
 function frame(testid, scenario) {
   const el = document.createElement('iframe'); el.dataset.testid = testid;
   el.src = PROVIDER + 'frame?scenario=' + scenario;
   el.width = 400; el.height = 160; container.append(el);
 }
 if (kind !== 'invisible' && kind !== 'hung') frame('checkbox-iframe', kind);
 window.addEventListener('message', event => {
   if (event.origin !== new URL(PROVIDER).origin) return;
   if (event.data === 'clicked') {
     if (kind === 'text' || kind === 'silhouette' || kind === 'unknown')
       frame('advanced-iframe', kind + '-challenge');
     else if (kind === 'checkbox') issue();
   }
   if (event.data === 'dragged' && kind === 'slider') issue();
 });
 if (kind === 'hung') setTimeout(() => { while (true) {} }, 500);
})();"""


async def fake_provider(route):
    url = urlsplit(route.request.url)
    if url.path == '/captcha.js':
        body = 'const TOKEN = ' + json.dumps(TOKEN) + '; const PROVIDER = ' + json.dumps(PROVIDER) + ';' + SCRIPT
        await route.fulfill(content_type='application/javascript', body=body)
        return
    kind = parse_qs(url.query).get('scenario', ['checkbox'])[0]
    if kind.endswith('-challenge'):
        modifier = {'text-challenge': '_image', 'silhouette-challenge': '_silhouette'}.get(kind, '')
        body = '<div class="AdvancedCaptcha AdvancedCaptcha' + modifier + '">Challenge</div>'
    elif kind == 'slider':
        body = """<style>.SliderCaptcha { width:300px; height:40px; position:relative; }
        [data-testid=thumb] {position:absolute; width:20px; height:40px; background:gray; touch-action:none;}</style>
        <div class="SliderCaptcha"><div data-testid="thumb" role="slider"></div></div>
        <script>
        const thumb = document.querySelector('[data-testid=thumb]'); let start;
        thumb.onpointerdown = e => {start=e.clientX; thumb.setPointerCapture(e.pointerId);};
        thumb.onpointerup = e => {
          if (e.clientX-start >= document.querySelector('.SliderCaptcha').offsetWidth * .9)
            parent.postMessage('dragged', '*');
        };
        </script>"""
    else:
        body = '<button id="js-button" role="checkbox" onclick="parent.postMessage(\'clicked\', \'*\')">Check</button>'
    await route.fulfill(content_type='text/html', body=body)


@pytest.fixture
def offline_browser(monkeypatch):
    manager = BrowserManager()
    original_new_page = manager.new_page

    async def new_page(**kwargs):
        page = await original_new_page(**kwargs)
        await page.route(PROVIDER + '**', fake_provider)
        return page

    monkeypatch.setattr(manager, 'new_page', new_page)
    monkeypatch.setattr(smartcaptcha, 'browser_manager', manager)
    monkeypatch.setattr(smartcaptcha, 'validate_page_url', lambda url: url)
    monkeypatch.setattr(smartcaptcha, 'DEADLINE_SECONDS', 3)
    return manager


def run_widget(manager, scenario):
    async def run():
        solver = smartcaptcha.SmartCaptchaSolver()
        try:
            return await asyncio.wait_for(solver.solve({
                'site_key': 'offline-key',
                'page_url': 'https://example.com/?scenario=' + scenario,
                'render_mode': 'widget',
            }), timeout=9)
        finally:
            await manager.close()
    return asyncio.run(run())


def test_Y1_checkbox(offline_browser, capsys):
    assert run_widget(offline_browser, 'checkbox') == {'token': TOKEN}
    assert TOKEN not in capsys.readouterr().out


def test_Y2_slider(offline_browser):
    assert run_widget(offline_browser, 'slider') == {'token': TOKEN}


def test_Y3_invisible(offline_browser):
    assert run_widget(offline_browser, 'invisible') == {'token': TOKEN}


def test_Y4_text_challenge(offline_browser):
    with pytest.raises(RuntimeError, match='text challenge is not supported yet'):
        run_widget(offline_browser, 'text')


def test_Y5_silhouette_challenge(offline_browser):
    with pytest.raises(RuntimeError, match='silhouette challenge is not supported yet'):
        run_widget(offline_browser, 'silhouette')


def test_Y5_unknown_challenge(offline_browser):
    with pytest.raises(RuntimeError, match='unknown challenge is not supported yet'):
        run_widget(offline_browser, 'unknown')


def test_Y6_parse_proxy():
    assert parse_proxy(None) is None
    assert parse_proxy('http://u:p%40ss@8.8.8.8:8080') == {
        'server': 'http://8.8.8.8:8080', 'username': 'u', 'password': 'p@ss'}
    assert parse_proxy('socks5://8.8.8.8:1080') == {'server': 'socks5://8.8.8.8:1080'}
    assert parse_proxy('https://[2001:4860:4860::8888]:443') == {
        'server': 'https://[2001:4860:4860::8888]:443'}
    for value in [
        'http://u:secret@8.8.8.8', 'ftp://u:secret@8.8.8.8:80',
        'http://u:secret@10.0.0.1:3128', 'http://u:secret@127.0.0.1:3128',
        'http://u:secret@localhost:3128', 'http://u:secret@sub.localhost.:3128',
        'http://user@8.8.8.8:80', 'http://:secret@8.8.8.8:80',
        'http://u:secret@8.8.8.8:0', 'http://u:secret@8.8.8.8:65536',
        'http://u:secret@[broken:80', 42, '',
    ]:
        with pytest.raises(ValueError) as error:
            parse_proxy(value)
        assert 'secret' not in str(error.value)
    for credentials in ['u:secret', 'u', 'u:']:
        with pytest.raises(ValueError, match='socks5 proxy with credentials is not supported'):
            parse_proxy('socks5://' + credentials + '@8.8.8.8:1080')


def test_Y6b_proxy_pins_ip(monkeypatch):
    def resolve(*addresses):
        return [(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM,
                 socket.IPPROTO_TCP, '', (ip, 3128)) for ip in addresses]

    def install(*addresses):
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: resolve(*addresses))

    install('8.8.4.4')
    assert parse_proxy('http://u:p@proxy.example:3128') == {
        'server': 'http://8.8.4.4:3128', 'username': 'u', 'password': 'p'}
    install('8.8.8.8', '8.8.4.4')
    assert parse_proxy('http://proxy.example:3128')['server'] == 'http://8.8.4.4:3128'
    for addresses in [('10.1.2.3',), ('8.8.8.8', '10.1.2.3'), ('fe80::1%eth0',), ()]:
        install(*addresses)
        with pytest.raises(ValueError):
            parse_proxy('http://u:p@proxy.example:3128')

    def failed(*args, **kwargs):
        raise socket.gaierror('DNS failed')
    monkeypatch.setattr(socket, 'getaddrinfo', failed)
    with pytest.raises(ValueError):
        parse_proxy('http://proxy.example:3128')


def test_Y7_proxy_context(monkeypatch):
    async def run():
        manager = BrowserManager()
        page = SimpleNamespace(close=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context),
                                  new_page=AsyncMock(return_value=page))
        monkeypatch.setattr(manager, 'get_browser', AsyncMock(return_value=browser))
        proxy = {'server': 'http://8.8.8.8:8080'}
        try:
            assert await manager.new_page(stealth=False, proxy=proxy) is page
            browser.new_context.assert_awaited_once_with(proxy=proxy)
            await manager.close_page(page)
            page.close.assert_awaited_once()
            context.close.assert_awaited_once()
            browser.new_context.reset_mock()
            context.close.reset_mock()
            await manager.new_page(stealth=False)
            browser.new_page.assert_awaited_once()
            browser.new_context.assert_not_awaited()
            await manager.close_page(page)
            context.close.assert_not_awaited()
        finally:
            await manager.close()
    asyncio.run(run())


@pytest.mark.parametrize('fail', [False, True])
def test_Y8_strip_proxy(tmp_path, monkeypatch, fail):
    engine = create_engine('sqlite:///' + str(tmp_path / 'tasks.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(task_worker, 'SessionLocal', factory)
    original = {'site_key': 'key', 'page_url': 'https://example.com/',
                'proxy': 'http://u:secret@8.8.8.8:80'}

    class Solver:
        async def solve(self, input_data):
            assert input_data == original
            if fail:
                raise RuntimeError('unsupported challenge')
            return {'token': TOKEN}

    async def run():
        db = factory()
        try:
            worker = task_worker.TaskWorker()
            worker.solvers['yandex_smartcaptcha'] = Solver()
            task = Task(api_key_id=1, type='yandex_smartcaptcha', input_data=json.dumps(original))
            db.add(task)
            db.commit()
            await worker.process_task(db, task)
            db.refresh(task)
            assert task.status == ('failed' if fail else 'solved')
            expected = {k: v for k, v in original.items() if k != 'proxy'}
            assert json.loads(task.input_data) == expected
            stuck = Task(api_key_id=1, type='yandex_smartcaptcha', status='processing',
                         input_data=json.dumps(original))
            db.add(stuck)
            db.commit()
            assert worker.recover_interrupted_tasks() == 1
            db.refresh(stuck)
            assert stuck.status == 'failed'
            assert json.loads(stuck.input_data) == expected
        finally:
            db.close()
            engine.dispose()
    asyncio.run(run())
    for raw in ['broken JSON', '[1, 2]', 'null', '42']:
        assert task_worker._strip_proxy(raw) == raw


def test_Y9_api_type(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models.api_key import User
    from app.config import settings

    monkeypatch.setattr(settings, 'admin_token', 'm4a-test-admin-token')

    engine = create_engine('sqlite:///' + str(tmp_path / 'api.db'),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def get_test_db():
        yield db

    app.dependency_overrides[get_db] = get_test_db
    try:
        user = User(username='m4a', password_hash='hash', password_salt='salt')
        db.add(user)
        db.commit()
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            response = client.post('/api/v1/api-key/' + str(user.id),
                                   headers={'Authorization': 'Bearer ' + settings.admin_token})
            assert response.status_code == 200, response.text
            response = client.post('/api/v1/task', headers={
                'Authorization': 'Bearer ' + response.json()['key']}, json={
                    'type': 'yandex_smartcaptcha', 'input_data': {
                        'site_key': 'key', 'page_url': 'https://example.com/'}})
            assert response.status_code in (200, 201), response.text
            assert response.json()['status'] == 'pending'
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_Y10_hung_page(offline_browser):
    start = time.monotonic()
    with pytest.raises(RuntimeError, match='no token'):
        run_widget(offline_browser, 'hung')
    assert time.monotonic() - start < 10
