"""Base classes for CAPTCHA solvers"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path


class BaseSolver(ABC):
    """Abstract base class for CAPTCHA solvers"""

    def __init__(self):
        self.vision_classifier = None
        self.config = {}

    @abstractmethod
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve CAPTCHA challenge

        Args:
            page: Playwright page object
            challenge_element: CAPTCHA challenge element
            **kwargs: Additional parameters

        Returns:
            True if solved successfully, False otherwise
        """
        pass

    @abstractmethod
    def detect(self, page) -> bool:
        """
        Detect if this CAPTCHA type is present on the page

        Args:
            page: Playwright page object

        Returns:
            True if this CAPTCHA type is detected
        """
        pass

    def configure(self, config: Dict[str, Any]):
        """Configure solver with custom settings"""
        self.config = config

    async def take_screenshot(self, element, path: Optional[Path] = None) -> bytes:
        """Take screenshot of CAPTCHA element"""
        return await element.screenshot(path=path)

    async def click_with_delay(self, element, min_delay: float = 0.3, max_delay: float = 0.7):
        """Click element with human-like delay"""
        import random
        import asyncio

        await asyncio.sleep(random.uniform(min_delay, max_delay))
        await element.click()


class CAPTCHAType:
    """CAPTCHA type identifiers"""

    # Google
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"

    # Yandex
    YANDEX_CAPTCHA = "yandex_captcha"
    YANDEX_SMART = "yandex_smart"

    # Cloudflare
    HCAPTCHA = "hcaptcha"
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"

    # Social networks
    VK_CAPTCHA = "vk_captcha"

    # Popular services
    FUN_CAPTCHA = "funcaptcha"  # Arkose Labs
    GEETEST = "geetest"  # GeeTest
    AMAZON_WAF = "amazon_waf"  # Amazon WAF
    TENCENT = "tencent"  # Tencent TenDI

    # Simple types
    SIMPLE_CAPTCHA = "simple_captcha"  # Text/Math/Rotate/Click
    IMAGE_TEXT = "image_text"  # Text on image

    UNKNOWN = "unknown"


class CAPTCHADetector:
    """Detect CAPTCHA type on a page"""

    @staticmethod
    async def detect_type(page) -> str:
        """
        Detect which CAPTCHA type is present

        Args:
            page: Playwright page object

        Returns:
            CAPTCHA type identifier
        """

        # Check for reCAPTCHA v2/v3
        if await page.locator('.g-recaptcha, iframe[src*="recaptcha"]').count() > 0:
            # Determine v2 or v3
            if await page.locator('.g-recaptcha-response').count() > 0:
                return CAPTCHAType.RECAPTCHA_V2
            return CAPTCHAType.RECAPTCHA_V3

        # Check for Yandex CAPTCHA
        if await page.locator('iframe[src*="captcha.yandex"], .yandex-captcha').count() > 0:
            return CAPTCHAType.YANDEX_CAPTCHA

        # Check for Yandex SmartCaptcha
        if await page.locator('iframe[src*="smartcaptcha"]').count() > 0:
            return CAPTCHAType.YANDEX_SMART

        # Check for hCaptcha
        if await page.locator('.h-captcha, iframe[src*="hcaptcha"]').count() > 0:
            return CAPTCHAType.HCAPTCHA

        # Check for Cloudflare Turnstile
        if await page.locator('iframe[src*="turnstile"], .cf-turnstile').count() > 0:
            return CAPTCHAType.CLOUDFLARE_TURNSTILE

        # Check for VK Captcha
        if await page.locator('img[src*="captcha"], .vk_captcha').count() > 0:
            if 'vk.com' in page.url or 'vk.ru' in page.url:
                return CAPTCHAType.VK_CAPTCHA

        # Check for FunCaptcha (Arkose Labs)
        if await page.locator('iframe[src*="funcaptcha"], .arkose-iframe').count() > 0:
            return CAPTCHAType.FUN_CAPTCHA

        # Check for GeeTest
        if await page.locator('iframe[src*="geetest"], .geetest-panel').count() > 0:
            return CAPTCHAType.GEETEST

        # Check for Amazon WAF
        if await page.locator('div[id*="captchachallenge"], img[src*="captcha"][src*="aws"]').count() > 0:
            return CAPTCHAType.AMAZON_WAF
        if 'aws.amazon.com/captcha' in page.url or 'captcha' in page.url.lower():
            return CAPTCHAType.AMAZON_WAF

        # Check for Tencent
        if await page.locator('iframe[src*="captcha.qq.com"], #TencentCaptcha').count() > 0:
            return CAPTCHAType.TENCENT
        if 'captcha.qq.com' in page.url:
            return CAPTCHAType.TENCENT

        # Check for simple CAPTCHA
        if await page.locator('img[src*="captcha"], input[name*="captcha"]').count() > 0:
            return CAPTCHAType.SIMPLE_CAPTCHA

        return CAPTCHAType.UNKNOWN


class SolverRegistry:
    """Registry for CAPTCHA solvers"""

    _solvers: Dict[str, BaseSolver] = {}

    @classmethod
    def register(cls, captcha_type: str, solver: BaseSolver):
        """Register a solver for a CAPTCHA type"""
        cls._solvers[captcha_type] = solver

    @classmethod
    def get(cls, captcha_type: str) -> Optional[BaseSolver]:
        """Get solver for a CAPTCHA type"""
        return cls._solvers.get(captcha_type)

    @classmethod
    def get_all(cls) -> Dict[str, BaseSolver]:
        """Get all registered solvers"""
        return cls._solvers.copy()