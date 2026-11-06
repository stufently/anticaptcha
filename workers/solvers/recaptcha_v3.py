"""reCAPTCHA v3 solver"""

import asyncio
import json
import random
from typing import Dict, Any, Optional

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        RECAPTCHA_V3 = "recaptcha_v3"


class RecaptchaV3Solver(BaseSolver):
    """
    Solver for reCAPTCHA v3

    reCAPTCHA v3 is score-based and doesn't show visible challenges.
    It requires a site key, page URL, and optional action parameter.
    """

    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.RECAPTCHA_V3

    async def detect(self, page) -> bool:
        """Check if reCAPTCHA v3 is present"""
        # v3 uses grecaptcha.execute() instead of render
        is_recaptcha = await page.locator('.g-recaptcha, script[src*="recaptcha"]').count() > 0

        # Check if it's v3 (no visible checkbox)
        if is_recaptcha:
            has_checkbox = await page.locator('.g-recaptcha-response').count() > 0
            return not has_checkbox

        return False

    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve reCAPTCHA v3

        Args:
            page: Playwright page
            challenge_element: Not used for v3
            **kwargs: Must include 'site_key', 'action' (optional)
        """
        try:
            print("🔍 Solving reCAPTCHA v3...")

            # Get parameters
            site_key = kwargs.get('site_key')
            action = kwargs.get('action', 'submit')

            if not site_key:
                # Try to extract from page
                site_key = await self._extract_site_key(page)

            if not site_key:
                print("❌ Site key not found")
                return False

            print(f"   Site key: {site_key[:30]}...")
            print(f"   Action: {action}")

            # Execute reCAPTCHA v3
            token = await page.evaluate('''
                async (params) => {
                    const { siteKey, action } = params;

                    return new Promise((resolve, reject) => {
                        if (typeof grecaptcha === 'undefined') {
                            reject(new Error('grecaptcha not loaded'));
                            return;
                        }

                        grecaptcha.execute(siteKey, { action: action })
                            .then(token => resolve(token))
                            .catch(error => reject(error));
                    });
                }
            ''', {'siteKey': site_key, 'action': action})

            if token:
                print(f"✅ Token received: {token[:50]}...")

                # Inject token into page
                await page.evaluate('''
                    (token) => {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = 'g-recaptcha-response';
                        input.value = token;
                        document.body.appendChild(input);
                    }
                ''', token)

                return True
            else:
                print("❌ No token received")
                return False

        except Exception as e:
            print(f"❌ Error solving reCAPTCHA v3: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _extract_site_key(self, page) -> Optional[str]:
        """Extract site key from page"""
        # Check data attribute
        site_key = await page.get_attribute('[data-sitekey]', 'data-sitekey')
        if site_key:
            return site_key

        # Check script content
        scripts = await page.locator('script').all()
        for script in scripts:
            content = await script.text_content()
            if 'sitekey' in content or 'siteKey' in content:
                import re
                match = re.search(r'["\']site[kK]ey["\']\s*:\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)

        return None