#!/usr/bin/env python3
"""Test VK Challenge solver on real VK"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from workers.solvers.unified import UnifiedCaptchaSolver


async def test_vk_challenge():
    """Test VK Challenge solver"""
    print("=" * 70)
    print("TESTING VK CHALLENGE SOLVER")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        # Navigate to VK
        print("\n🌐 Navigating to VK...")
        await page.goto('https://vk.com', timeout=60000, wait_until='networkidle')
        await asyncio.sleep(2)

        url = page.url
        print(f"URL: {url}")

        # Check if challenge detected
        from workers.solvers.base import CAPTCHADetector
        captcha_type = await CAPTCHADetector.detect_type(page)

        print(f"\n🤖 Detected: {captcha_type}")

        if captcha_type == "vk_challenge":
            print("✅ VK Challenge detected!")

            # Try to solve
            print("\n🔄 Attempting to solve...")
            result = await solver.solve(page)

            print(f"\n📊 Result: {result}")

            if result['success']:
                print("✅ VK Challenge PASSED!")
                print(f"   Final URL: {page.url}")

                # Try to access VK features
                print("\n🔍 Checking VK access...")

                # Check for login elements
                has_email = await page.locator('input[name="email"]').count() > 0
                has_feed = await page.locator('#feed_rows').count() > 0

                print(f"   Login form: {has_email}")
                print(f"   Feed visible: {has_feed}")

                return True
            else:
                print("❌ VK Challenge NOT passed")
                print(f"   Error: {result.get('error', 'unknown')}")
                return False
        else:
            print("⚠️ VK Challenge not detected")
            print(f"   Type: {captcha_type}")
            print("   VK may allow access from this IP")

            # Screenshot
            await page.screenshot(path='vk_no_challenge.png')
            print("   Screenshot: vk_no_challenge.png")

            return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await page.close()
        await browser_manager.close()
        await solver.cleanup()


async def main():
    success = await test_vk_challenge()

    print("\n" + "=" * 70)
    if success:
        print("✅ VK CHALLENGE TEST PASSED!")
    else:
        print("❌ VK CHALLENGE TEST FAILED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())