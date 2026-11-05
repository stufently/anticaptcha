"""Base CAPTCHA solver class"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseSolver(ABC):
    """Abstract base class for CAPTCHA solvers"""
    
    def __init__(self):
        self.browser = None
    
    @abstractmethod
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve CAPTCHA
        
        Args:
            input_data: CAPTCHA parameters (site_key, page_url, etc.)
        
        Returns:
            Solution dict with 'token' or 'text' key
        """
        pass
    
    @abstractmethod
    async def setup(self):
        """Initialize solver (load models, start browser, etc.)"""
        pass
    
    @abstractmethod
    async def cleanup(self):
        """Clean up resources (close browser, etc.)"""
        pass