"""Yandex CAPTCHA solver"""

import asyncio
import random
from typing import Dict, Any
from pathlib import Path

from workers.solvers.base import BaseSolver, CAPTCHAType


class YandexCaptchaSolver(BaseSolver):
    """Solver for Yandex CAPTCHA (image selection)"""

    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.YANDEX_CAPTCHA

    async def detect(self, page) -> bool:
        """Check if Yandex CAPTCHA is present"""
        selectors = [
            'iframe[src*="captcha.yandex"]',
            '.yandex-captcha',
            'div[class*="captcha"] img[src*="yandex"]'
        ]

        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True

        return False

    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve Yandex CAPTCHA

        Yandex CAPTCHA typically shows:
        - 3x3 or 4x4 grid of images
        - "Select all images with X" instruction
        - Similar to reCAPTCHA but with Yandex styling
        """
        try:
            print("🔍 Solving Yandex CAPTCHA...")

            # Find the challenge iframe
            iframe = None
            for selector in ['iframe[src*="captcha.yandex"]', '.yandex-captcha iframe']:
                if await page.locator(selector).count() > 0:
                    iframe = page.frame_locator(selector)
                    break

            if not iframe:
                print("❌ Yandex CAPTCHA iframe not found")
                return False

            # Get instruction
            instruction_elem = iframe.locator('.captcha-instruction, .challenge-instruction, h2')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else ""

            print(f"   Instruction: {instruction[:100]}")

            # Get images
            images = await iframe.locator('.captcha-image, .challenge-image, img').all()

            if not images:
                print("❌ No images found in Yandex CAPTCHA")
                return False

            print(f"   Found {len(images)} images")

            # Take screenshot of the entire challenge
            challenge_screenshot = await iframe.locator('.captcha-container, .challenge-container').screenshot()

            # Use Vision LLM to classify
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()

                # Determine grid size
                grid_size = "3x3" if len(images) == 9 else "4x4" if len(images) == 16 else "2x3"

                # Classify
                indices = await classifier.classify_tiles(
                    challenge_screenshot,
                    f"Select all tiles with {instruction}",
                    grid_size
                )

                print(f"   Vision LLM selected: {indices}")

                # Click images
                for idx in indices:
                    if 0 <= idx < len(images):
                        await self.click_with_delay(images[idx])

            else:
                print("⚠️ No vision classifier available")
                return False

            # Submit
            submit_button = iframe.locator('.captcha-submit, button[type="submit"], .verify-button')
            if await submit_button.count() > 0:
                await self.click_with_delay(submit_button)

            print("✅ Yandex CAPTCHA solved")
            return True

        except Exception as e:
            print(f"❌ Error solving Yandex CAPTCHA: {e}")
            import traceback
            traceback.print_exc()
            return False


class YandexSmartCaptchaSolver(BaseSolver):
    """Solver for Yandex SmartCaptcha (text + behavioral)"""

    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.YANDEX_SMART

    async def detect(self, page) -> bool:
        """Check if Yandex SmartCaptcha is present"""
        selectors = [
            'iframe[src*="smartcaptcha"]',
            '.smart-captcha',
            'div[class*="smartcaptcha"]'
        ]

        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True

        return False

    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve Yandex SmartCaptcha

        SmartCaptcha uses:
        - Text input challenges
        - Image recognition
        - Behavioral analysis
        """
        try:
            print("🔍 Solving Yandex SmartCaptcha...")

            # Find iframe
            iframe = page.frame_locator('iframe[src*="smartcaptcha"]')

            # Check challenge type
            if await iframe.locator('input[type="text"]').count() > 0:
                # Text challenge
                return await self._solve_text_challenge(iframe)

            elif await iframe.locator('img, .challenge-image').count() > 0:
                # Image challenge
                return await self._solve_image_challenge(iframe)

            else:
                # Behavioral - just wait
                await asyncio.sleep(random.uniform(2, 4))
                return True

        except Exception as e:
            print(f"❌ Error solving Yandex SmartCaptcha: {e}")
            return False

    async def _solve_text_challenge(self, iframe) -> bool:
        """Solve text input challenge"""
        # TODO: Implement text recognition
        print("   Text challenge detected (not implemented yet)")
        return False

    async def _solve_image_challenge(self, iframe) -> bool:
        """Solve image selection challenge"""
        # Similar to regular Yandex CAPTCHA
        solver = YandexCaptchaSolver()
        solver.vision_classifier = self.vision_classifier
        return await solver.solve(iframe, None)