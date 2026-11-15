#!/usr/bin/env python3
"""Test just hCaptcha"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.hcaptcha import HcaptchaSolver
from app.utils.browser import browser_manager


async def test_hcaptcha():
    """Test hCaptcha with longer timeout"""
    print("\n" + "="*70)
    print("🧪 Test: hCaptcha (with longer timeout)")
    print("="*70)

    solver = HcaptchaSolver()
    await solver.setup()

    try:
        result = await solver.solve({
            "site_key": "a5f74b19-9e45-40e0-b45d-47ff91b7a6c2",
            "page_url": "https://accounts.hcaptcha.com/demo"
        })

        if result.get('token'):
            print(f"\n✅✅✅ SUCCESS! hCaptcha token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n❌ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


if __name__ == "__main__":
    result = asyncio.run(test_hcaptcha())
    sys.exit(0 if result else 1)