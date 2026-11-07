"""VK Challenge solver - handles VK behavior-based challenge"""

import asyncio
import random
import re
from typing import Dict, Any

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        VK_CHALLENGE = "vk_challenge"


class VKChallengeSolver(BaseSolver):
    """
    Solver for VK Challenge (behavior-based protection)

    VK Challenge не является CAPTCHA с картинками.
    Это behavior-based защита которая проверяет:
    - User agent
    - Behavior patterns
    - Browser fingerprint
    - JavaScript execution

    Решение:
    1. Обнаружить challenge страницу
    2. Кликнуть "Продолжить"
    3. Ждать редиректа
    4. Повторить если нужно
    """

    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.VK_CHALLENGE
        self.max_attempts = 5

    async def detect(self, page) -> bool:
        """Check if VK Challenge is present"""
        # Check URL
        is_vk = 'vk.com' in page.url or 'vk.ru' in page.url
        is_challenge = 'challenge.html' in page.url

        if is_vk and is_challenge:
            return True

        # Check page title
        try:
            title = await page.title()
            if 'Проверяем, что вы не робот' in title or 'Checking that you are not a robot' in title:
                return True
        except:
            pass

        # Check for challenge button
        if await page.locator('button:has-text("Продолжить")').count() > 0:
            return True

        if await page.locator('button:has-text("Continue")').count() > 0:
            return True

        return False

    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve VK Challenge

        Args:
            page: Playwright page
            challenge_element: Not used
            **kwargs: Optional parameters
        """
        try:
            print("🔍 Solving VK Challenge...")

            for attempt in range(self.max_attempts):
                print(f"   Attempt {attempt + 1}/{self.max_attempts}")

                # Check if still on challenge
                if 'challenge.html' not in page.url:
                    print("   ✅ Challenge passed!")
                    return True

                # Find "Continue" button
                continue_selectors = [
                    'button:has-text("Продолжить")',
                    'button:has-text("Continue")',
                    '.start',
                    'button[type="button"]',
                ]

                button = None
                for selector in continue_selectors:
                    if await page.locator(selector).count() > 0:
                        button = page.locator(selector).first
                        break

                if button:
                    # Add human-like delay
                    await asyncio.sleep(random.uniform(1, 2))

                    # Click button
                    print("   🖱️ Clicking 'Continue' button...")
                    await button.click()

                    # Wait for redirect
                    await asyncio.sleep(random.uniform(3, 5))

                    # Check if redirected
                    new_url = page.url
                    print(f"   URL: {new_url[:60]}...")

                    if 'challenge.html' not in new_url:
                        print("   ✅ Challenge passed!")
                        return True
                    else:
                        print("   ⚠️ Still on challenge, retrying...")
                else:
                    print("   ❌ Button not found")
                    return False

            print(f"❌ Failed after {self.max_attempts} attempts")
            return False

        except Exception as e:
            print(f"❌ Error solving VK Challenge: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def wait_for_pass(self, page, timeout: int = 60) -> bool:
        """
        Wait for VK challenge to pass

        Args:
            page: Playwright page
            timeout: Max wait time in seconds

        Returns:
            True if challenge passed
        """
        try:
            print("⏳ Waiting for VK Challenge to pass...")

            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                # Check if challenge passed
                if 'challenge.html' not in page.url:
                    print("✅ Challenge passed!")
                    return True

                # Wait a bit
                await asyncio.sleep(1)

            print("❌ Timeout waiting for challenge to pass")
            return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False


# Register with CAPTCHA types
if hasattr(CAPTCHAType, 'VK_CHALLENGE'):
    CAPTCHAType.VK_CHALLENGE = "vk_challenge"