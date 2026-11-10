"""Base classes for CAPTCHA solvers"""

import asyncio
import random
from typing import Dict, Any, Optional
from pathlib import Path


class BaseSolver:
    """Base class for all CAPTCHA solvers"""

    def __init__(self):
        self.vision_classifier = None

    async def setup(self):
        """Setup solver (override in subclass)"""
        pass

    async def cleanup(self):
        """Cleanup resources (override in subclass)"""
        pass

    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve CAPTCHA

        Args:
            page: Playwright page
            challenge_element: CAPTCHA element
            **kwargs: Additional parameters

        Returns:
            True if solved successfully
        """
        raise NotImplementedError("Subclass must implement solve()")

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
    VK_CHALLENGE = "vk_challenge"  # VK behavior-based protection

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

        Uses wait_for to handle async iframe loading.

        Args:
            page: Playwright page object

        Returns:
            CAPTCHA type identifier
        """

        try:
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

            # Check for hCaptcha - wait for async iframe load
            # Try multiple selectors including site-specific
            hcaptcha_selectors = [
                '.h-captcha',
                'iframe[src*="hcaptcha"]',
                'iframe[src*="newassets.hcaptcha.com"]',
                '.hcaptcha',
                'div[data-hcaptcha-widget-id]',
            ]

            for selector in hcaptcha_selectors:
                try:
                    # Wait up to 5s for iframe to appear
                    await page.wait_for_selector(selector, timeout=5000)
                    return CAPTCHAType.HCAPTCHA
                except Exception:
                    pass

            # Check for Cloudflare Turnstile - wait for async load
            turnstile_selectors = [
                'iframe[src*="turnstile"]',
                '.cf-turnstile',
                'iframe[src*="challenges.cloudflare.com"]',
                'div[data-sitekey] iframe',  # Turnstile widget structure
            ]

            for selector in turnstile_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    return CAPTCHAType.CLOUDFLARE_TURNSTILE
                except Exception:
                    pass

            # Check for VK Captcha
            if await page.locator('img[src*="captcha"], .vk_captcha').count() > 0:
                if 'vk.com' in page.url or 'vk.ru' in page.url:
                    return CAPTCHAType.VK_CAPTCHA

            # Check for VK Challenge (behavior-based protection)
            if 'vk.com' in page.url or 'vk.ru' in page.url:
                if 'challenge.html' in page.url:
                    return CAPTCHAType.VK_CHALLENGE

            # Check for FunCaptcha (Arkose Labs)
            if await page.locator('iframe[src*="funcaptcha"], .arkose-iframe, #fc-iframe-wrap').count() > 0:
                return CAPTCHAType.FUN_CAPTCHA

            # Check for GeeTest
            if await page.locator('iframe[src*="geetest"], .geetest-panel, .gee-test').count() > 0:
                return CAPTCHAType.GEETEST

            # Check for Amazon WAF - specific only
            if 'aws.amazon.com/captcha' in page.url:
                if await page.locator('div[id*="captchachallenge"]').count() > 0:
                    return CAPTCHAType.AMAZON_WAF
            if 'amazon' in page.url or 'aws' in page.url:
                if await page.locator('img[src*="captcha"][src*="aws"]').count() > 0:
                    return CAPTCHAType.AMAZON_WAF

            # Check for Tencent
            if await page.locator('iframe[src*="captcha.qq.com"], #TencentCaptcha').count() > 0:
                return CAPTCHAType.TENCENT
            if 'captcha.qq.com' in page.url:
                return CAPTCHAType.TENCENT

            # Check for simple CAPTCHA - case-insensitive alt matching
            # Use CSS :has() for combined checks
            simple_selectors = [
                'img[alt*="CAPTCHA" i]',
                'img[alt*="captcha" i]',
                'img[alt*="Captcha" i]',
                '.captcha-image img',
                '#captcha img',
                'img[src*="securimage"]',
            ]

            has_captcha_image = False
            for selector in simple_selectors:
                if await page.locator(selector).count() > 0:
                    has_captcha_image = True
                    break

            if has_captcha_image:
                if await page.locator('input[name*="captcha" i], input[placeholder*="captcha" i]').count() > 0:
                    return CAPTCHAType.SIMPLE_CAPTCHA

            return CAPTCHAType.UNKNOWN

        except Exception as e:
            print(f"⚠️ Error detecting CAPTCHA: {e}")
            return CAPTCHAType.UNKNOWN


class SolverRegistry:
    """Registry for CAPTCHA solvers"""

    _solvers = {}

    @classmethod
    def register(cls, captcha_type: str, solver: BaseSolver):
        """Register a solver for a CAPTCHA type"""
        cls._solvers[captcha_type] = solver

    @classmethod
    def get(cls, captcha_type: str) -> Optional[BaseSolver]:
        """Get solver for a CAPTCHA type"""
        return cls._solvers.get(captcha_type)

    @classmethod
    def list_all(cls) -> Dict[str, BaseSolver]:
        """Get all registered solvers"""
        return cls._solvers.copy()