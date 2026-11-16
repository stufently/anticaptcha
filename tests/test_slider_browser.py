"""Slider solver against local pages in the real Chromium of the image.

No network: the page URL is a fictitious https host answered by page.route,
and the SSRF guard is replaced by identity (it would resolve DNS). Like the
other offline browser tests (test_m4b_gaps.py), these run wherever Playwright's
Chromium is installed, which includes the CI image test step.
"""
import asyncio

import pytest

from app.utils.browser import BrowserManager
from workers.solvers import slider

ORIGIN = 'https://www.slider.test'
PAGE_URL = ORIGIN + '/login?x=1'

# Shared drag logic. The handle follows the mouse inside a 300px track; a
# release at >= 250px counts as a pass. `onPass` decides what a pass looks
# like, `onFail` what a short drag does.
DRAG_JS = """
const handle = document.getElementById(HANDLE_ID);
let down = false, startX = 0, maxLeft = 0;
handle.addEventListener('mousedown', e => { down = true; startX = e.clientX; maxLeft = 0; });
document.addEventListener('mousemove', e => {
  if (!down) return;
  const left = Math.max(0, Math.min(260, e.clientX - startX));
  handle.style.left = left + 'px';
  maxLeft = Math.max(maxLeft, left);
});
document.addEventListener('mouseup', () => {
  if (!down) return;
  down = false;
  window.drags = (window.drags || 0) + 1;
  if (PASSES && maxLeft >= 250) onPass(); else handle.style.left = '0px';
});
"""

TRACK_STYLE = 'position:relative;width:300px;height:34px;background:#ddd;margin:40px'
HANDLE_STYLE = 'position:absolute;left:0;top:0;width:40px;height:34px;background:#888'

# (a) nc-like markup of a widget that hides the handle on a pass (it stays in the DOM),
# the track (#nc_1__scale_text.nc_scale) stays visible with a new text, a cookie is
# set from script and the URL changes, so the result must carry the FINAL url.
NC_PAGE = f"""<!doctype html><html><body>
<div id="nc_1__scale_text" class="nc_scale" style="{TRACK_STYLE}">
  <span class="nc-lang-cnt">slide to verify</span>
  <span id="nc_1_n1z" class="nc_iconfont btn_slide" style="{HANDLE_STYLE}"></span>
</div>
<script>
const HANDLE_ID = 'nc_1_n1z', PASSES = true;
function onPass() {{
  handle.style.display = 'none';
  document.querySelector('#nc_1__scale_text .nc-lang-cnt').textContent = 'verified';
  document.cookie = 'nc_pass=1; path=/';
  history.pushState({{}}, '', '/done');
}}
{DRAG_JS}
</script></body></html>"""

# (b) A hidden copy of handle and track comes first in the DOM (a template).
# Only the visible pair can be dragged; the hidden one has no bounding box.
DUPLICATE_PAGE = f"""<!doctype html><html><body>
<div class="slider-track" style="display:none">
  <span class="slider-handle" id="hidden-handle"></span>
</div>
<div class="slider-track" id="real-track" style="{TRACK_STYLE}">
  <span class="slider-handle" id="real-handle" style="{HANDLE_STYLE}"></span>
</div>
<script>
const HANDLE_ID = 'real-handle', PASSES = true;
function onPass() {{ handle.style.display = 'none'; }}
{DRAG_JS}
</script></body></html>"""

# (c) The slider never accepts: the handle springs back after every drag.
STUCK_PAGE = DUPLICATE_PAGE.replace('PASSES = true', 'PASSES = false')

# (d) The widget hides the handle while it "verifies" (longer than the 1.5 s
# wait after the drag) and then rejects: the handle comes back.
REJECT_LATE_PAGE = DUPLICATE_PAGE.replace(
    "function onPass() { handle.style.display = 'none'; }",
    "function onPass() { handle.style.display = 'none';"
    " setTimeout(() => { handle.style.left = '0px'; handle.style.display = ''; }, 2500); }")


# (e)/(f) The DOM real Alibaba nc (AWSC nc 1.97.0, renderTo "nc") builds, as
# snapshotted live from the vendor demo (appkey CF_APP_1, TEST_PASS/TEST_BLOCK).
# A pass keeps the handle VISIBLE at the end of the track and only swaps its
# class btn_slide -> btn_ok, with "验证通过" as the text; a block replaces the
# whole slider with div.errloading, so the handle is gone. Both outcomes arrive
# after a server round trip (setTimeout here).
NC_REAL_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="nc" style="margin:40px;width:300px" class="sm-pop-inner nc-container">
 <div class="nc_1_nocaptcha" id="nc_1_nocaptcha"><div id="nc_1_wrapper" class="nc_wrapper">
  <div id="nc_1_n1t" class="nc_scale" style="position:relative;width:300px;height:34px;background:#e8e8e8">
   <div id="nc_1__bg" class="nc_bg" style="width:0px;position:absolute;height:100%"></div>
   <span id="nc_1_n1z" class="nc_iconfont btn_slide" aria-label="滑块" tabindex="0" role="button"
     style="left:0px;position:absolute;top:0;width:40px;height:34px;background:#fff;z-index:2"></span>
   <div id="nc_1__scale_text" class="scale_text slidetounlock"
     style="width:100%;height:100%;position:absolute;z-index:1"><span class="nc-lang-cnt"
     data-nc-lang="SLIDE">请按住滑块，拖动到最右边</span></div>
  </div></div></div></div>
<script>
const HANDLE_ID = 'nc_1_n1z', PASSES = true;
function onPass() { setTimeout(OUTCOME, 400); }
function pass() {
  handle.className = 'nc_iconfont btn_ok';
  handle.style.left = '258px';
  document.getElementById('nc_1__scale_text').innerHTML =
    '<span class="nc-lang-cnt" data-nc-lang="SLIDE"><b>验证通过</b></span>';
}
function block() {
  document.getElementById('nc_1_wrapper').innerHTML =
    '<div id="`nc_1_refresh1`" class="errloading"><i id="`nc_1_refresh2`"' +
    ' class="nc_iconfont icon_warn"></i>验证失败，点击框体重试(error:iv6prg)</div>';
}
const OUTCOME = OUTCOME_FN;
DRAG_JS_HERE
</script></body></html>""".replace('DRAG_JS_HERE', DRAG_JS)
NC_REAL_PASS_PAGE = NC_REAL_PAGE.replace('OUTCOME_FN', 'pass')
NC_REAL_BLOCK_PAGE = NC_REAL_PAGE.replace('OUTCOME_FN', 'block')


# (g) A passed nc next to a slider that never accepts: the pass marker belongs
# to the nc handle only and must not turn the stuck slider into a success.
PASSED_NC_BLOCK = """<div class="nc-container"><div id="nc_1_n1t" class="nc_scale"
 style="position:relative;width:300px;height:34px"><span id="nc_1_n1z" class="nc_iconfont btn_ok"
 style="position:absolute;left:258px;width:40px;height:34px;background:#fff"></span></div></div>"""
STUCK_WITH_PASSED_NC_PAGE = STUCK_PAGE.replace('<body>', '<body>' + PASSED_NC_BLOCK, 1)
# (h) The same passed nc next to a second nc that was blocked.
BLOCKED_WITH_PASSED_NC_PAGE = NC_REAL_BLOCK_PAGE.replace(
    '<body>', '<body>' + PASSED_NC_BLOCK.replace('nc_1_', 'nc_2_'), 1)


# (i) Real nc retry: on a block nc writes div.errloading into its wrapper and
# binds a ONE-SHOT mousedown on the wrapper that calls reset(), which rebuilds
# the slider with a fresh #nc_1_n1z (nc.js 1.97.0, functions i/s). The reset
# here takes RESET_DELAY ms, longer than the 500 ms pause after a failed drag,
# so a solver that does not wait for the handle runs out of attempts. OUTCOMES
# says what each successive drag gets; the last entry repeats.
NC_RETRY_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
OTHER_NC
<div id="nc" style="margin:40px;width:300px" class="sm-pop-inner nc-container">
 <div class="nc_1_nocaptcha" id="nc_1_nocaptcha"><div id="nc_1_wrapper" class="nc_wrapper">
  <div id="nc_1_n1t" class="nc_scale" style="position:relative;width:300px;height:34px;background:#e8e8e8">
   <span id="nc_1_n1z" class="nc_iconfont btn_slide" role="button"
     style="left:0px;position:absolute;top:0;width:40px;height:34px;background:#fff;z-index:2"></span>
   <div id="nc_1__scale_text" class="scale_text slidetounlock"
     style="width:100%;height:100%;position:absolute;z-index:1"><span class="nc-lang-cnt"
     data-nc-lang="SLIDE">请按住滑块，拖动到最右边</span></div>
  </div></div></div></div>
<script>
const OUTCOMES = OUTCOMES_LIST, RESET_DELAY = 1500, RESETS = RESETS_ON, VERDICT_DELAY = VERDICT_MS;
const wrapper = document.getElementById('nc_1_wrapper');
const SLIDER_HTML = wrapper.innerHTML;
window.drags = 0; window.resets = 0; window.wrongClicks = 0;
let handle, down = false, startX = 0, maxLeft = 0;
function bind() {
  handle = document.getElementById('nc_1_n1z');
  handle.addEventListener('mousedown', e => { down = true; startX = e.clientX; maxLeft = 0; });
}
bind();
document.addEventListener('mousemove', e => {
  if (!down) return;
  const left = Math.max(0, Math.min(260, e.clientX - startX));
  handle.style.left = left + 'px';
  maxLeft = Math.max(maxLeft, left);
});
document.addEventListener('mouseup', () => {
  if (!down) return;
  down = false;
  window.drags += 1;
  if (maxLeft < 250) { handle.style.left = '0px'; return; }
  const outcome = OUTCOMES[Math.min(window.drags, OUTCOMES.length) - 1];
  setTimeout(outcome === 'pass' ? pass : block, VERDICT_DELAY);
});
function pass() {
  handle.className = 'nc_iconfont btn_ok';
  handle.style.left = '258px';
  document.getElementById('nc_1__scale_text').innerHTML =
    '<span class="nc-lang-cnt" data-nc-lang="SLIDE"><b>验证通过</b></span>';
}
function block() {
  wrapper.innerHTML = '<div id="`nc_1_refresh1`" class="errloading"><i id="`nc_1_refresh2`"' +
    ' class="nc_iconfont icon_warn"></i>验证失败，点击框体重试(error:iv6prg)</div>';
  if (!RESETS) return;
  wrapper.addEventListener('mousedown', function once() {
    wrapper.removeEventListener('mousedown', once);
    window.resets += 1;
    setTimeout(() => { wrapper.innerHTML = SLIDER_HTML; bind(); }, RESET_DELAY);
  });
}
const other = document.getElementById('nc_9_wrapper');
if (other) other.addEventListener('mousedown', () => { window.wrongClicks += 1; });
</script></body></html>"""
# A second nc on the page, before ours in the DOM, already showing its own
# failure box: clicking it is the wrong retry.
OTHER_BLOCKED_NC = """<div class="nc-container" style="margin:40px;width:300px">
 <div id="nc_9_wrapper" class="nc_wrapper"><div class="errloading"
 style="padding:7px 5px">验证失败，点击框体重试(error:other)</div></div></div>"""


def nc_retry_page(outcomes, resets=True, other=False, verdict_ms=400):
    return (NC_RETRY_PAGE.replace('OUTCOMES_LIST', repr(list(outcomes)))
            .replace('VERDICT_MS', str(verdict_ms))
            .replace('RESETS_ON', 'true' if resets else 'false')
            .replace('OTHER_NC', OTHER_BLOCKED_NC if other else ''))


def run_page(monkeypatch, html, *, after_page=None):
    """Solve PAGE_URL served as `html`; returns (result or exception, info)."""
    info = {}

    async def scenario():
        manager = BrowserManager()
        monkeypatch.setattr(slider, 'browser_manager', manager)
        monkeypatch.setattr(slider, 'validate_page_url', lambda url: url)

        async def serve(route):
            info['header_user_agent'] = await route.request.header_value('user-agent')
            await route.fulfill(
                status=200, content_type='text/html', body=html,
                headers={'Set-Cookie': 'sid=abc; Path=/; Secure'},
            )

        new_page = manager.new_page

        async def routed_page(**kwargs):
            page = await new_page(**kwargs)
            await page.context.add_cookies([
                {'name': 'foreign', 'value': 'x', 'domain': 'other.test', 'path': '/'},
                {'name': 'sibling', 'value': 'y', 'domain': 'cdn.slider.test', 'path': '/'},
                {'name': 'sub', 'value': 'z', 'domain': 'api.www.slider.test', 'path': '/'},
                {'name': 'parent', 'value': '1', 'domain': '.slider.test', 'path': '/'},
                {'name': 'parent_host', 'value': 'h', 'domain': 'slider.test', 'path': '/'},
            ])
            await page.route(ORIGIN + '/**', serve)
            original_goto = page.goto

            async def goto(url, **kw):
                response = await original_goto(url, **kw)
                if after_page is not None:
                    await after_page(page, info)
                return response

            page.goto = goto
            original_close = page.close

            async def close(**kw):
                info['drags'] = await page.evaluate('window.drags || 0')
                info['resets'] = await page.evaluate('window.resets || 0')
                info['wrong_clicks'] = await page.evaluate('window.wrongClicks || 0')
                info['final_dom'] = {
                    'handle_in_dom': await page.locator('#nc_1_n1z').count() == 1,
                    'handle_visible': await page.locator('#nc_1_n1z').is_visible(),
                    'track_visible': await page.locator('#nc_1__scale_text').is_visible(),
                }
                return await original_close(**kw)

            page.close = close
            return page

        monkeypatch.setattr(manager, 'new_page', routed_page)
        solver = slider.SliderCaptchaSolver()
        try:
            return await solver.solve({'page_url': PAGE_URL})
        except Exception as exc:  # returned for the assertions
            return exc
        finally:
            await manager.close()

    return asyncio.run(scenario()), info


def test_nc_slider_hidden_handle_with_track_left_is_success(monkeypatch):
    async def page_user_agent(page, info):
        info['page_user_agent'] = await page.evaluate('navigator.userAgent')

    result, info = run_page(monkeypatch, NC_PAGE, after_page=page_user_agent)

    assert not isinstance(result, Exception), result
    assert result['success'] is True
    assert info['drags'] == 1
    assert result['url'] == ORIGIN + '/done'
    # navigator.userAgent of the page, the same value its HTTP requests send
    assert result['user_agent'] == info['page_user_agent']
    assert result['user_agent'] == info['header_user_agent']
    assert result['user_agent'].startswith('Mozilla/5.0')
    assert 'Headless' not in result['user_agent']
    by_name = {c['name']: c for c in result['cookies']}
    # host, script, parent domain and subdomain cookies; other sites dropped
    assert set(by_name) == {'sid', 'nc_pass', 'parent', 'sub'}
    assert by_name['sid']['value'] == 'abc'
    assert by_name['parent']['domain'] == '.slider.test'
    assert by_name['nc_pass']['value'] == '1'
    # the page really is in the state the success check must accept
    assert info['final_dom'] == {'handle_in_dom': True, 'handle_visible': False,
                                 'track_visible': True}


def test_hidden_duplicate_handle_is_skipped(monkeypatch):
    async def locate_in_browser(page, info):
        solver = slider.SliderCaptchaSolver()
        handle = await solver._locate(page, solver.SLIDER_HANDLES)
        track = await solver._locate(page, solver.SLIDER_TRACKS)
        info['located'] = (await handle.get_attribute('id'), await track.get_attribute('id'))

    result, info = run_page(monkeypatch, DUPLICATE_PAGE, after_page=locate_in_browser)

    assert info['located'] == ('real-handle', 'real-track')
    assert not isinstance(result, Exception), result
    assert result['success'] is True
    assert info['drags'] == 1


def test_slider_that_stays_is_failed(monkeypatch):
    result, info = run_page(monkeypatch, STUCK_PAGE)

    assert isinstance(result, RuntimeError)
    assert str(result) == 'Slider still present after 3 attempts'
    # every attempt really dragged the visible handle
    assert info['drags'] == 3


def test_handle_hidden_during_verification_then_back_is_failed(monkeypatch):
    result, info = run_page(monkeypatch, REJECT_LATE_PAGE)

    assert isinstance(result, RuntimeError)
    assert str(result) == 'Slider still present after 3 attempts'
    assert info['drags'] == 3


def test_real_nc_pass_with_visible_btn_ok_handle_is_success(monkeypatch):
    result, info = run_page(monkeypatch, NC_REAL_PASS_PAGE)

    assert not isinstance(result, Exception), result
    assert result['success'] is True
    assert info['drags'] == 1
    # the state real nc leaves after a pass: the handle is still there and visible
    assert info['final_dom'] == {'handle_in_dom': True, 'handle_visible': True,
                                 'track_visible': True}


def test_real_nc_block_without_reset_is_a_clear_failure(monkeypatch):
    """The retry box is clicked, but this page never rebuilds the slider."""
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 1000)
    result, info = run_page(monkeypatch, NC_REAL_BLOCK_PAGE)

    assert isinstance(result, RuntimeError)
    assert info['drags'] == 1
    assert 'slider did not come back within 1 s after clicking the retry box' in str(result)
    assert info['final_dom']['handle_in_dom'] is False


def test_real_nc_block_retry_box_click_brings_slider_back_and_passes(monkeypatch):
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 4000)
    result, info = run_page(monkeypatch, nc_retry_page(['block', 'pass']))

    assert not isinstance(result, Exception), result
    assert result['success'] is True
    # one block, one click on the retry box, one more drag of the NEW handle
    assert (info['drags'], info['resets']) == (2, 1)
    assert info['final_dom'] == {'handle_in_dom': True, 'handle_visible': True,
                                 'track_visible': True}


def test_real_nc_late_verdict_is_awaited_before_the_retry(monkeypatch):
    """The block arrives 2.5 s after the release (live nc took 1-3 s), after
    the fixed 1.5 s wait of the drag: the handle waits slid out meanwhile. The
    solver must wait for that verdict, click the box it brings and pass on the
    next drag instead of judging the pending slide."""
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 4000)
    result, info = run_page(monkeypatch, nc_retry_page(['block', 'pass'], verdict_ms=2500))

    assert not isinstance(result, Exception), result
    assert result['success'] is True
    assert (info['drags'], info['resets']) == (2, 1)


def test_real_nc_blocking_every_attempt_is_failed(monkeypatch):
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 4000)
    result, info = run_page(monkeypatch, nc_retry_page(['block']))

    assert isinstance(result, RuntimeError)
    assert str(result) == 'Slider rejected by Alibaba nc after 3 attempts'
    # every attempt dragged; the last block is not clicked away
    assert (info['drags'], info['resets']) == (3, 2)


def test_retry_clicks_the_box_of_the_dragged_nc_only(monkeypatch):
    """Another nc on the page shows its own failure box (before ours in the
    DOM). Only the box of the dragged nc is clicked. The foreign box keeps the
    page from passing, so the task still fails, but never through it."""
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 4000)
    result, info = run_page(monkeypatch, nc_retry_page(['block', 'pass'], other=True))

    assert isinstance(result, RuntimeError)
    assert info['wrong_clicks'] == 0
    assert (info['drags'], info['resets']) == (2, 1)


def test_passed_nc_does_not_mask_a_stuck_slider(monkeypatch):
    result, info = run_page(monkeypatch, STUCK_WITH_PASSED_NC_PAGE)

    assert isinstance(result, RuntimeError)
    assert str(result) == 'Slider still present after 3 attempts'
    # every attempt dragged the live slider, not the already passed nc handle
    assert info['drags'] == 3


def test_passed_nc_does_not_mask_a_blocked_nc(monkeypatch):
    monkeypatch.setattr(slider, 'NC_RESET_TIMEOUT_MS', 1000)
    result, info = run_page(monkeypatch, BLOCKED_WITH_PASSED_NC_PAGE)

    assert isinstance(result, RuntimeError)
    assert info['drags'] == 1
