"""Integration test for slider solver through worker"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from workers.task_worker import SOLVERS


@pytest.mark.asyncio
async def test_slider_solver_registered():
    """Test that slider solver is registered in SOLVERS"""
    assert 'slider' in SOLVERS
    assert SOLVERS['slider'].__name__ == 'SliderCaptchaSolver'


@pytest.mark.asyncio
async def test_slider_solver_interface():
    """Test that slider solver has correct interface for worker"""
    solver_class = SOLVERS['slider']
    solver = solver_class()
    
    # Check that solve method exists and accepts input_data
    assert hasattr(solver, 'solve')
    
    # Test with missing page_url - should raise ValueError
    with pytest.raises(ValueError, match='page_url is required'):
        await solver.solve({})


@pytest.mark.asyncio
async def test_slider_solver_ssrf_protection():
    """Test that slider solver has SSRF protection"""
    solver_class = SOLVERS['slider']
    solver = solver_class()
    
    # Test localhost - should raise PageURLRejected
    from workers.solvers.url_guard import PageURLRejected
    
    with pytest.raises(PageURLRejected, match='localhost'):
        await solver.solve({'page_url': 'http://localhost:8080'})
    
    # Test private IP - should raise PageURLRejected
    with pytest.raises(PageURLRejected, match='not public'):
        await solver.solve({'page_url': 'http://192.168.1.1'})
    
    # Test file:// protocol - should raise PageURLRejected
    with pytest.raises(PageURLRejected, match='scheme'):
        await solver.solve({'page_url': 'file:///etc/passwd'})


@pytest.mark.asyncio
async def test_slider_solver_custom_selectors():
    """Test that slider solver accepts custom selectors"""
    solver_class = SOLVERS['slider']
    solver = solver_class()
    
    # Just verify that custom selectors are accepted without validation error
    # Full integration test requires real browser
    input_data = {
        'page_url': 'https://example.com/captcha',
        'handle_selector': '#custom-handle',
        'track_selector': '#custom-track'
    }
    
    # Should not raise validation error
    from workers.solvers.slider import _selectors
    handle_selectors = _selectors(input_data.get('handle_selector'), solver.SLIDER_HANDLES, 'handle_selector')
    track_selectors = _selectors(input_data.get('track_selector'), solver.SLIDER_TRACKS, 'track_selector')
    
    assert handle_selectors == ['#custom-handle']
    assert track_selectors == ['#custom-track']
