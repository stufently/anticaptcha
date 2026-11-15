#!/usr/bin/env python3
"""Test just Turnstile (easiest to solve)"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.turnstile import TurnstileSolver
from app.utils.browser import browser_manager


async def test_turnstile():
    """Test Turnstile with extended timeout"""
    print("\n" + "="*70)
    print("🧪 Test: Cloudflare Turnstile (should auto-solve)")
    print("="*70)

    solver = TurnstileSolver()
    await solver.setup()

    try:
        result = await solver.solve({
            "site_key": "0x4AAAAAAASGzhKmSbZ3bF5k",
            "page_url": "https://demo.turnstile.workers.dev/"
        })

        if result.get('token'):
            print(f"\n✅✅✅ SUCCESS! Turnstile token: {result['token'][:80]}...")
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
    result = asyncio.run(test_turnstile())
    sys.exit(0 if result else 1)