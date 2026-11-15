#!/usr/bin/env python3
"""Test just ONE reCAPTCHA for quick verification"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.recaptcha import RecaptchaV2Solver
from app.utils.browser import browser_manager


async def test_one_recaptcha():
    """Test a single reCAPTCHA"""
    print("\n" + "="*70)
    print("🧪 Quick Test: Google reCAPTCHA Demo")
    print("="*70)

    solver = RecaptchaV2Solver()
    await solver.setup()

    try:
        result = await solver.solve({
            "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
            "page_url": "https://www.google.com/recaptcha/api2/demo"
        })

        if result.get('token'):
            print(f"\n✅✅✅ SUCCESS! Token received: {result['token'][:80]}...")
            return True
        else:
            print(f"\n❌ No token received")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


if __name__ == "__main__":
    result = asyncio.run(test_one_recaptcha())
    sys.exit(0 if result else 1)