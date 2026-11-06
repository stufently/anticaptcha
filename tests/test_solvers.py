#!/usr/bin/env python3
"""Comprehensive tests for CAPTCHA solvers"""

import asyncio
import pytest
import sys
sys.path.insert(0, '/app')

from workers.solvers.base import BaseSolver, CAPTCHAType, CAPTCHADetector, SolverRegistry
from workers.solvers.unified import UnifiedCaptchaSolver


class TestCAPTCHATypes:
    """Test CAPTCHA type definitions"""

    def test_all_types_defined(self):
        """Check all CAPTCHA types are defined"""
        types = [
            CAPTCHAType.RECAPTCHA_V2,
            CAPTCHAType.RECAPTCHA_V3,
            CAPTCHAType.YANDEX_CAPTCHA,
            CAPTCHAType.YANDEX_SMART,
            CAPTCHAType.HCAPTCHA,
            CAPTCHAType.CLOUDFLARE_TURNSTILE,
            CAPTCHAType.VK_CAPTCHA,
            CAPTCHAType.FUN_CAPTCHA,
            CAPTCHAType.GEETEST,
            CAPTCHAType.AMAZON_WAF,
            CAPTCHAType.TENCENT,
            CAPTCHAType.SIMPLE_CAPTCHA,
        ]

        for captcha_type in types:
            assert isinstance(captcha_type, str)
            assert len(captcha_type) > 0


class TestSolverRegistry:
    """Test solver registry"""

    def test_register_and_get(self):
        """Test registering and retrieving solvers"""
        # Create mock solver
        class MockSolver(BaseSolver):
            async def solve(self, page, challenge_element, **kwargs):
                return True

        solver = MockSolver()
        SolverRegistry.register("test_captcha", solver)

        retrieved = SolverRegistry.get("test_captcha")
        assert retrieved is solver

    def test_get_nonexistent(self):
        """Test getting nonexistent solver"""
        result = SolverRegistry.get("nonexistent_type")
        assert result is None

    def test_list_all(self):
        """Test listing all solvers"""
        solvers = SolverRegistry.list_all()
        assert isinstance(solvers, dict)


class TestUnifiedCaptchaSolver:
    """Test unified CAPTCHA solver"""

    @pytest.mark.asyncio
    async def test_setup(self):
        """Test solver setup"""
        solver = UnifiedCaptchaSolver()
        await solver.setup()

        assert solver._initialized is True
        assert solver.vision_classifier is not None

        await solver.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test solver cleanup"""
        solver = UnifiedCaptchaSolver()
        await solver.setup()
        await solver.cleanup()

        assert solver._initialized is False


class TestCAPTCHADetector:
    """Test CAPTCHA detection"""

    @pytest.mark.asyncio
    async def test_detect_recaptcha_v2(self):
        """Test reCAPTCHA v2 detection"""
        from unittest.mock import AsyncMock, MagicMock

        page = MagicMock()
        page.locator = MagicMock()

        # Mock .g-recaptcha exists
        locator = MagicMock()
        locator.count = AsyncMock(return_value=1)
        page.locator.return_value = locator

        # Mock .g-recaptcha-response exists
        response_locator = MagicMock()
        response_locator.count = AsyncMock(return_value=1)

        def locator_side_effect(selector):
            if '.g-recaptcha-response' in selector:
                return response_locator
            return locator

        page.locator.side_effect = locator_side_effect

        result = await CAPTCHADetector.detect_type(page)
        assert result == CAPTCHAType.RECAPTCHA_V2

    @pytest.mark.asyncio
    async def test_detect_unknown(self):
        """Test unknown CAPTCHA detection"""
        from unittest.mock import MagicMock, AsyncMock

        page = MagicMock()
        page.url = "https://example.com"
        page.locator = MagicMock()
        page.wait_for_selector = MagicMock()

        # Mock all locators return 0
        locator = MagicMock()
        locator.count = AsyncMock(return_value=0)
        page.locator.return_value = locator

        # Mock wait_for raises timeout
        from playwright.async_api import TimeoutError
        page.wait_for_selector.side_effect = TimeoutError("timeout")

        result = await CAPTCHADetector.detect_type(page)
        assert result == CAPTCHAType.UNKNOWN


class TestBaseSolver:
    """Test base solver"""

    @pytest.mark.asyncio
    async def test_setup(self):
        """Test base solver setup"""
        solver = BaseSolver()
        await solver.setup()
        # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test base solver cleanup"""
        solver = BaseSolver()
        await solver.cleanup()
        # Should not raise

    def test_vision_classifier(self):
        """Test vision classifier attribute"""
        solver = BaseSolver()
        solver.vision_classifier = "test"
        assert solver.vision_classifier == "test"


class TestSolversImport:
    """Test that all solvers can be imported"""

    def test_import_recaptcha_v2(self):
        """Test importing RecaptchaV2Solver"""
        from workers.solvers.recaptcha import RecaptchaV2Solver
        solver = RecaptchaV2Solver()
        assert solver is not None

    def test_import_recaptcha_v3(self):
        """Test importing RecaptchaV3Solver"""
        from workers.solvers.recaptcha_v3 import RecaptchaV3Solver
        solver = RecaptchaV3Solver()
        assert solver is not None

    def test_import_funcaptcha(self):
        """Test importing FunCaptchaSolver"""
        from workers.solvers.funcaptcha import FunCaptchaSolver
        solver = FunCaptchaSolver()
        assert solver is not None

    def test_import_geetest(self):
        """Test importing GeeTestSolver"""
        from workers.solvers.geetest import GeeTestSolver
        solver = GeeTestSolver()
        assert solver is not None

    def test_import_amazon(self):
        """Test importing AmazonWAFSolver"""
        from workers.solvers.amazon import AmazonWAFSolver
        solver = AmazonWAFSolver()
        assert solver is not None

    def test_import_tencent(self):
        """Test importing TencentCaptchaSolver"""
        from workers.solvers.tencent import TencentCaptchaSolver
        solver = TencentCaptchaSolver()
        assert solver is not None

    def test_import_simple(self):
        """Test importing SimpleCaptchaSolver"""
        from workers.solvers.simple_captcha import SimpleCaptchaSolver
        solver = SimpleCaptchaSolver()
        assert solver is not None

    def test_import_hcaptcha(self):
        """Test importing HcaptchaSolver"""
        from workers.solvers.hcaptcha import HcaptchaSolver
        solver = HcaptchaSolver()
        assert solver is not None

    def test_import_cloudflare(self):
        """Test importing CloudflareTurnstileSolver"""
        from workers.solvers.cloudflare import CloudflareTurnstileSolver
        solver = CloudflareTurnstileSolver()
        assert solver is not None

    def test_import_yandex(self):
        """Test importing YandexCaptchaSolver"""
        from workers.solvers.yandex import YandexCaptchaSolver, YandexSmartCaptchaSolver
        solver1 = YandexCaptchaSolver()
        solver2 = YandexSmartCaptchaSolver()
        assert solver1 is not None
        assert solver2 is not None

    def test_import_vk(self):
        """Test importing VKCaptchaSolver"""
        from workers.solvers.vk import VKCaptchaSolver
        solver = VKCaptchaSolver()
        assert solver is not None


class TestVisionLLMClassifier:
    """Test Vision LLM classifier"""

    def test_import_vision_llm(self):
        """Test importing VisionLLMClassifier"""
        from workers.classifiers.vision_llm import VisionLLMClassifier
        classifier = VisionLLMClassifier()
        assert classifier is not None

    def test_vision_llm_methods(self):
        """Test VisionLLMClassifier has required methods"""
        from workers.classifiers.vision_llm import VisionLLMClassifier
        classifier = VisionLLMClassifier()

        assert hasattr(classifier, 'classify_tiles')
        assert hasattr(classifier, 'cleanup')


class TestAllSolversRegistration:
    """Test that all solvers are registered"""

    @pytest.mark.asyncio
    async def test_all_solvers_registered(self):
        """Test all 12 solvers are registered"""
        solver = UnifiedCaptchaSolver()
        await solver.setup()

        expected_types = [
            CAPTCHAType.RECAPTCHA_V2,
            CAPTCHAType.RECAPTCHA_V3,
            CAPTCHAType.YANDEX_CAPTCHA,
            CAPTCHAType.YANDEX_SMART,
            CAPTCHAType.HCAPTCHA,
            CAPTCHAType.CLOUDFLARE_TURNSTILE,
            CAPTCHAType.VK_CAPTCHA,
            CAPTCHAType.FUN_CAPTCHA,
            CAPTCHAType.GEETEST,
            CAPTCHAType.AMAZON_WAF,
            CAPTCHAType.TENCENT,
            CAPTCHAType.SIMPLE_CAPTCHA,
        ]

        for captcha_type in expected_types:
            registered_solver = SolverRegistry.get(captcha_type)
            assert registered_solver is not None, f"Solver {captcha_type} not registered"

        await solver.cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])