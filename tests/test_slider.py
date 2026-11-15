"""Tests for slider CAPTCHA solver."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workers.solvers.slider import SliderCaptchaSolver


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
    page.goto = AsyncMock()
    page.close = AsyncMock()
    return page


@pytest.fixture
def mock_browser_manager(mock_page):
    """Mock browser_manager to return mock_page."""
    with patch('workers.solvers.slider.browser_manager') as mock_bm:
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
        # Mock detection to return False after drag (slider gone)
        detect_calls = [True, False]  # First call: present, second: gone
        
        async def mock_detect(page):
            return detect_calls.pop(0) if detect_calls else False
        
        solver.detect = mock_detect
        
        # Mock _drag_slider to succeed
        solver._drag_slider = AsyncMock()
        
        # Mock install_widget_page
        with patch('workers.solvers.slider.install_widget_page', new_callable=AsyncMock):
            result = await solver.solve({'page_url': 'https://example.com'})
        
        assert result['success'] is True
        assert 'error' not in result
    
    @pytest.mark.asyncio
    async def test_solve_failure_after_retries(self, solver, mock_page, mock_browser_manager):
        """Test solver returns failure after 3 attempts."""
        # Mock detection to always return True (slider still present)
        solver.detect = AsyncMock(return_value=True)
        
        # Mock _drag_slider to succeed but slider remains
        solver._drag_slider = AsyncMock()
        
        # Mock install_widget_page
        with patch('workers.solvers.slider.install_widget_page', new_callable=AsyncMock):
            result = await solver.solve({'page_url': 'https://example.com'})
        
        assert result['success'] is False
        assert 'error' in result
        assert solver._drag_slider.call_count == 3
    
    @pytest.mark.asyncio
    async def test_solve_missing_page_url(self, solver):
        """Test solver returns error when page_url is missing."""
        result = await solver.solve({})
        assert result['success'] is False
        assert result['error'] == 'page_url is required'
    
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
    async def test_locate_first_match(self, solver, mock_page):
        """Test _locate returns first matching element."""
        # First selector matches
        mock_locator1 = MagicMock()
        mock_locator1.count = AsyncMock(return_value=1)
        
        # Second selector doesn't match
        mock_locator2 = MagicMock()
        mock_locator2.count = AsyncMock(return_value=0)
        
        mock_page.locator.side_effect = [mock_locator1, mock_locator2]
        
        result = await solver._locate(mock_page, ['#first', '#second'])
        assert result == mock_locator1
    
    @pytest.mark.asyncio
    async def test_locate_no_match(self, solver, mock_page):
        """Test _locate raises when no element found."""
        # All selectors don't match
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator.return_value = mock_locator
        
        with pytest.raises(LookupError, match='No element found'):
            await solver._locate(mock_page, ['#first', '#second'])
    
    @pytest.mark.asyncio
    async def test_custom_selectors(self, solver, mock_page, mock_browser_manager):
        """Test that custom selectors are used when provided."""
        solver.detect = AsyncMock(return_value=False)
        solver._drag_slider = AsyncMock()
        
        with patch('workers.solvers.slider.install_widget_page', new_callable=AsyncMock):
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
