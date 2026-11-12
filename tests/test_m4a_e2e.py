"""Live Yandex probe; no network unless explicitly enabled."""
import asyncio
import os

import pytest

from app.utils.browser import browser_manager
from workers.solvers.smartcaptcha import SmartCaptchaSolver

pytestmark = pytest.mark.skipif(os.getenv('ANTICAPTCHA_E2E') != '1', reason='live provider opt-in')


def test_E8_yandex_demo():
    async def run():
        try:
            try:
                result = await SmartCaptchaSolver().solve({
                    'site_key': 'FEXfAbHQsToo97VidNVk3j4dC74nGW1DgdxjtNB9',
                    'page_url': 'https://captcha-api.yandex.ru/demo',
                    'render_mode': 'widget',
                })
            except RuntimeError as error:
                # A datacenter IP always gets a task: any of the solver's own
                # terminal errors is fine, a crash or a hang is not.
                assert any(m in str(error) for m in (
                    'challenge is not supported yet', 'needs the vision LLM',
                    'not solved in', 'no token within'))
            else:
                assert isinstance(result['token'], str)
                assert len(result['token']) >= 50
        finally:
            await browser_manager.close()
    asyncio.run(run())
