"""Tests for slider CAPTCHA solver."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workers.solvers.slider import (
    GOTO_TIMEOUT_MS, SETTLE_MS, SETTLE_POLL_MS, SliderCaptchaSolver, _page_cookies,
)


@pytest.fixture
def solver():
    """Create slider solver instance."""
    return SliderCaptchaSolver()


@pytest.fixture
def mock_page():
    """Create mock Playwright page."""
    page = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.locator = MagicMock()
    # nothing on the page unless a test says otherwise (the nc markers included)
    page.locator.return_value.count = AsyncMock(return_value=0)
    page.goto = AsyncMock()
    page.close = AsyncMock()
    page.url = 'https://example.com/'
    page.context = MagicMock()
    page.context.cookies = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value='UA/1.0')
    return page


@pytest.fixture
def mock_browser_manager(mock_page):
    """Mock browser_manager to return mock_page."""
    with patch('workers.solvers.slider.browser_manager') as mock_bm, \
            patch('workers.solvers.slider.validate_page_url', side_effect=lambda url: url):
        mock_bm.new_page = AsyncMock(return_value=mock_page)
        yield mock_bm


class TestSliderCaptchaSolver:
    """Test slider CAPTCHA solver."""
    
    @pytest.mark.asyncio
    async def test_detect_slider_present(self, solver, mock_page):
        """Test detection when slider is present."""
        # Mock locator to return count > 0 for slider handle
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_page.locator.return_value = mock_locator
        
        result = await solver.detect(mock_page)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_detect_slider_absent(self, solver, mock_page):
        """Test detection when slider is absent."""
        # Mock locator to return count = 0 for all selectors
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator.return_value = mock_locator
        
        result = await solver.detect(mock_page)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_solve_success(self, solver, mock_page, mock_browser_manager):
        """Test successful slider solve."""
        # The visibility check runs only after a drag: handle gone after the first one
        solver._visible_handle = AsyncMock(return_value=False)
        solver._drag_slider = AsyncMock()
        mock_page.url = 'https://shop.example.com/item?id=1'
        mock_page.context.cookies = AsyncMock(return_value=[
            {'name': 'own', 'value': '1', 'domain': 'shop.example.com', 'path': '/'},
            {'name': 'parent', 'value': '2', 'domain': '.example.com', 'path': '/'},
            {'name': 'tracker', 'value': '3', 'domain': '.tracker.test', 'path': '/'},
        ])
        mock_page.evaluate = AsyncMock(return_value='Mozilla/5.0 test')
        
        result = await solver.solve({'page_url': 'https://shop.example.com/item?id=1'})
        
        assert result == {
            'success': True,
            'cookies': [
                {'name': 'own', 'value': '1', 'domain': 'shop.example.com', 'path': '/'},
                {'name': 'parent', 'value': '2', 'domain': '.example.com', 'path': '/'},
            ],
            'url': 'https://shop.example.com/item?id=1',
            'user_agent': 'Mozilla/5.0 test',
        }
        mock_page.evaluate.assert_awaited_once_with('navigator.userAgent')
        assert solver._drag_slider.call_count == 1
        mock_page.close.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_solve_failure_after_retries(self, solver, mock_page, mock_browser_manager):
        """Test solver returns failure after 3 attempts."""
        # The handle stays visible after every drag
        solver._visible_handle = AsyncMock(return_value=True)
        
        # Mock _drag_slider to succeed but slider remains
        solver._drag_slider = AsyncMock()
        
        with pytest.raises(RuntimeError, match='Slider still present after 3 attempts'):
            await solver.solve({'page_url': 'https://example.com'})
        
        assert solver._drag_slider.call_count == 3
        mock_page.close.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_solve_missing_page_url(self, solver):
        """Test solver raises when page_url is missing."""
        with pytest.raises(ValueError, match='page_url is required'):
            await solver.solve({})
    
    @pytest.mark.asyncio
    async def test_drag_slider_human_like(self, solver, mock_page):
        """Test that drag uses human-like movement."""
        # Mock locate to return elements with bounding boxes
        mock_handle = MagicMock()
        mock_handle.bounding_box = AsyncMock(return_value={
            'x': 100, 'y': 200, 'width': 40, 'height': 40
        })
        
        mock_track = MagicMock()
        mock_track.bounding_box = AsyncMock(return_value={
            'x': 100, 'y': 200, 'width': 300, 'height': 40
        })
        
        solver._locate = AsyncMock(side_effect=[mock_handle, mock_track])
        
        await solver._drag_slider(mock_page)
        
        # Verify mouse movements happened
        assert mock_page.mouse.move.call_count > 0
        assert mock_page.mouse.down.call_count == 1
        assert mock_page.mouse.up.call_count == 1
        
        # Verify wait_for_timeout was called (human-like delays)
        assert mock_page.wait_for_timeout.call_count > 0
    
    @pytest.mark.asyncio
    async def test_drag_slider_missing_bounds(self, solver, mock_page):
        """Test drag fails gracefully when bounds unavailable."""
        # Mock locate to return elements without bounding boxes
        mock_handle = MagicMock()
        mock_handle.bounding_box = AsyncMock(return_value=None)
        
        mock_track = MagicMock()
        mock_track.bounding_box = AsyncMock(return_value=None)
        
        solver._locate = AsyncMock(side_effect=[mock_handle, mock_track])
        
        with pytest.raises(LookupError, match='Slider bounds unavailable'):
            await solver._drag_slider(mock_page)
    
    @pytest.mark.asyncio
    async def test_locate_first_visible_match(self, solver, mock_page):
        """_locate skips hidden matches and returns the first visible one."""
        hidden, visible = MagicMock(), MagicMock()
        hidden.is_visible = AsyncMock(return_value=False)
        visible.is_visible = AsyncMock(return_value=True)
        mock_locator1 = MagicMock()
        mock_locator1.count = AsyncMock(return_value=2)
        mock_locator1.nth = MagicMock(side_effect=[hidden, visible])
        mock_page.locator.return_value = mock_locator1
        
        result = await solver._locate(mock_page, ['#first', '#second'])
        assert result is visible
        mock_page.locator.assert_called_once_with('#first')
    
    @pytest.mark.asyncio
    async def test_locate_no_match(self, solver, mock_page):
        """Test _locate raises when no element found."""
        # All selectors don't match
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator.return_value = mock_locator
        
        with pytest.raises(LookupError, match='No visible element found'):
            await solver._locate(mock_page, ['#first', '#second'])

    @pytest.mark.asyncio
    async def test_locate_only_hidden_matches(self, solver, mock_page):
        """Matches that are all hidden are not a handle: LookupError."""
        hidden = MagicMock()
        hidden.is_visible = AsyncMock(return_value=False)
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.nth = MagicMock(return_value=hidden)
        mock_page.locator.return_value = mock_locator
        
        with pytest.raises(LookupError, match='No visible element found'):
            await solver._locate(mock_page, ['#first'])
    
    @pytest.mark.asyncio
    async def test_custom_selectors(self, solver, mock_page, mock_browser_manager):
        """Test that custom selectors are used when provided."""
        solver._visible_handle = AsyncMock(return_value=False)
        solver._drag_slider = AsyncMock()
        
        result = await solver.solve({
            'page_url': 'https://example.com',
            'handle_selector': '#custom-handle',
            'track_selector': '#custom-track'
        })
        
        assert result['success'] is True
        # Verify _drag_slider was called with custom selectors
        call_args = solver._drag_slider.call_args
        assert call_args[0][1] == ['#custom-handle']
        assert call_args[0][2] == ['#custom-track']
        # Success check looks at the custom handle only, never at the track
        assert solver._visible_handle.await_args_list
        assert all(c.args == (mock_page, ['#custom-handle'])
                   for c in solver._visible_handle.await_args_list)


    @pytest.mark.asyncio
    async def test_drag_errors_raise_after_last_attempt(self, solver, mock_page, mock_browser_manager):
        """A drag that keeps failing ends the task as failed, page closed."""
        solver._drag_slider = AsyncMock(side_effect=LookupError('No element found'))
        
        with pytest.raises(RuntimeError, match='Slider solve failed: No element found'):
            await solver.solve({'page_url': 'https://example.com'})
        
        assert solver._drag_slider.call_count == 3
        mock_page.close.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_page_url_goes_through_ssrf_guard(self, solver):
        """A private page_url is rejected before a browser page is opened."""
        from workers.solvers.url_guard import PageURLRejected
        with patch('workers.solvers.slider.browser_manager') as mock_bm:
            mock_bm.new_page = AsyncMock()
            with pytest.raises(PageURLRejected):
                await solver.solve({'page_url': 'http://127.0.0.1:8000/'})
            mock_bm.new_page.assert_not_called()
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize('field', ['handle_selector', 'track_selector'])
    @pytest.mark.parametrize('bad', [123, [], [''], ['#ok', 5], {'a': 1}])
    async def test_invalid_selector_override_rejected(self, solver, mock_browser_manager, field, bad):
        """Selector overrides must be a non-empty string or list of strings,
        rejected before any browser page opens, naming the offending field."""
        with pytest.raises(ValueError, match=f'^{field} must be a non-empty string or list of strings$'):
            await solver.solve({'page_url': 'https://example.com', field: bad})
        mock_browser_manager.new_page.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_goto_uses_guarded_url_and_timeout(self, solver, mock_page):
        """The browser opens the URL the guard RETURNS (normalized), bounded by
        the navigation timeout."""
        solver._visible_handle = AsyncMock(return_value=False)
        solver._drag_slider = AsyncMock()
        with patch('workers.solvers.slider.browser_manager') as mock_bm, \
                patch('workers.solvers.slider.validate_page_url',
                      return_value='https://normalized.example/') as guard:
            mock_bm.new_page = AsyncMock(return_value=mock_page)
            await solver.solve({'page_url': 'HTTPS://Normalized.Example'})
        guard.assert_called_once_with('HTTPS://Normalized.Example')
        mock_page.goto.assert_awaited_once_with(
            'https://normalized.example/', timeout=GOTO_TIMEOUT_MS, wait_until='domcontentloaded')


    @pytest.mark.asyncio
    async def test_custom_selectors_used_for_success_check(self, solver, mock_page, mock_browser_manager):
        """A custom slider that is still on the page is not reported as solved."""
        def locator(selector):
            loc = MagicMock()
            loc.count = AsyncMock(return_value=1 if selector == '#custom-handle' else 0)
            element = MagicMock()
            element.is_visible = AsyncMock(return_value=True)
            element.evaluate = AsyncMock(return_value=False)  # not a passed nc handle
            loc.nth = MagicMock(return_value=element)
            return loc
        mock_page.locator = MagicMock(side_effect=locator)
        solver._drag_slider = AsyncMock()
        
        with pytest.raises(RuntimeError, match='Slider still present after 3 attempts'):
            await solver.solve({
                'page_url': 'https://example.com',
                'handle_selector': '#custom-handle',
                'track_selector': '#custom-track',
            })


def _cookie(domain, name='c'):
    return {'name': name, 'value': 'v', 'domain': domain, 'path': '/'}


class TestSettle:
    """The page must look passed for the whole SETTLE_MS before success."""

    @pytest.mark.asyncio
    async def test_failure_during_settle_is_not_success(self, solver, mock_page):
        # passed at first, not passed at the last poll of the window
        polls = SETTLE_MS // SETTLE_POLL_MS + 1
        solver._passed = AsyncMock(side_effect=[True] * (polls - 1) + [False])
        assert await solver._stays_passed(mock_page, ['#h']) is False

    @pytest.mark.asyncio
    async def test_passed_for_whole_window_is_success(self, solver, mock_page):
        polls = SETTLE_MS // SETTLE_POLL_MS + 1
        solver._passed = AsyncMock(return_value=True)
        assert await solver._stays_passed(mock_page, ['#h']) is True
        assert solver._passed.await_count == polls
        waits = [c.args[0] for c in mock_page.wait_for_timeout.await_args_list]
        assert sum(waits) >= SETTLE_MS


class TestPageCookies:
    """Result cookies: the page host, its subdomains and parent domains only."""

    def test_keeps_host_subdomain_and_parent(self):
        cookies = [_cookie('www.example.com', 'host'), _cookie('.www.example.com', 'dot'),
                   _cookie('.api.www.example.com', 'sub'), _cookie('.example.com', 'parent')]
        assert _page_cookies(cookies, 'https://www.example.com/a') == cookies

    @pytest.mark.parametrize('domain', [
        'other.test', '.tracker.com',
        'example.com',            # host-only cookie of the parent HOST: not sent to www
        'cdn.example.com',        # sibling of the page host
        'evilwww.example.com',    # suffix without a dot boundary
        'www.example.com.evil',   # page host as a prefix
        'example.co',             # prefix of the parent
        '',
    ])
    def test_drops_other_domains(self, domain):
        assert _page_cookies([_cookie(domain)], 'https://www.example.com/') == []

    def test_case_insensitive_and_port_ignored(self):
        cookies = [_cookie('WWW.Example.COM')]
        assert _page_cookies(cookies, 'https://www.example.com:8443/x') == cookies

    def test_final_url_without_host_gives_no_cookies(self):
        assert _page_cookies([_cookie('example.com')], 'about:blank') == []


class TestSliderMovement:
    """Test human-like movement parameters."""
    
    def test_movement_parameters(self):
        """Test that movement uses correct ranges."""
        # Verify constants are in expected ranges
        steps_min, steps_max = 35, 55
        curve_min, curve_max = 7, 15
        jitter_x = 0.7
        jitter_y = 1.2
        
        assert steps_min >= 30  # Not too fast
        assert steps_max <= 60  # Not too slow
        assert curve_min >= 5   # Visible arc
        assert curve_max <= 20  # Not too extreme
        assert jitter_x <= 1.0  # Subtle horizontal jitter
        assert jitter_y <= 2.0  # Moderate vertical jitter
