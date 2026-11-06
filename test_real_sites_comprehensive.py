#!/usr/bin/env python3
"""Comprehensive test on real websites with CAPTCHA"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from workers.solvers.unified import UnifiedCaptchaSolver


async def test_recaptcha_v2():
    """Test reCAPTCHA v2 on Google demo"""
    print("=" * 70)
    print("TEST: reCAPTCHA v2 - Google Demo")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        await page.goto('https://www.google.com/recaptcha/api2/demo', timeout=60000)
        print("✅ Page loaded")

        # Solve
        result = await solver.solve(page)

        print(f"\nResult: {result}")

        if result['success']:
            print("✅ reCAPTCHA v2 SOLVED!")
            return True
        else:
            print(f"⚠️ Not solved: {result.get('error', 'unknown')}")
            # Check if auto-verified
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            if token:
                print(f"✅ Auto-verified! Token: {token[:50]}...")
                return True
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await page.close()
        await solver.cleanup()


async def test_hcaptcha():
    """Test hCaptcha on demo site"""
    print("\n" + "=" * 70)
    print("TEST: hCaptcha - Demo Site")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        # hCaptcha demo
        await page.goto('https://accounts.hcaptcha.com/demo', timeout=60000)
        print("✅ Page loaded")

        # Solve
        result = await solver.solve(page)

        print(f"\nResult: {result}")

        if result['success']:
            print("✅ hCaptcha SOLVED!")
            return True
        else:
            print(f"⚠️ Not solved: {result.get('error', 'unknown')}")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        await page.close()
        await solver.cleanup()


async def test_turnstile():
    """Test Cloudflare Turnstile"""
    print("\n" + "=" * 70)
    print("TEST: Cloudflare Turnstile - Demo")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        # Cloudflare Turnstile demo
        await page.goto('https://challenges.cloudflare.com/turnstile/', timeout=60000)
        print("✅ Page loaded")

        # Solve
        result = await solver.solve(page)

        print(f"\nResult: {result}")

        if result['success']:
            print("✅ Turnstile SOLVED!")
            return True
        else:
            print(f"⚠️ Not solved: {result.get('error', 'unknown')}")

            # Check for token
            token = await page.evaluate('''
                () => document.querySelector('[name="cf-turnstile-response"]')?.value
            ''')
            if token:
                print(f"✅ Token received: {token[:50]}...")
                return True
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        await page.close()
        await solver.cleanup()


async def test_simple_captcha():
    """Test simple text CAPTCHA"""
    print("\n" + "=" * 70)
    print("TEST: Simple CAPTCHA - PHP Captcha")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        await page.goto('https://www.phpcaptcha.org/try-securimage/', timeout=60000)
        print("✅ Page loaded")

        # Solve
        result = await solver.solve(page)

        print(f"\nResult: {result}")

        if result['success']:
            print("✅ Simple CAPTCHA SOLVED!")
            return True
        else:
            print(f"⚠️ Not solved: {result.get('error', 'unknown')}")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        await page.close()
        await solver.cleanup()


async def test_geetest():
    """Test GeeTest CAPTCHA"""
    print("\n" + "=" * 70)
    print("TEST: GeeTest - Demo")
    print("=" * 70)

    solver = UnifiedCaptchaSolver()
    await solver.setup()

    page = await browser_manager.new_page()

    try:
        # GeeTest demo (from 2captcha)
        await page.goto('https://2captcha.com/demo/geetest', timeout=60000)
        print("✅ Page loaded")

        # Solve
        result = await solver.solve(page)

        print(f"\nResult: {result}")

        if result['success']:
            print("✅ GeeTest SOLVED!")
            return True
        else:
            print(f"⚠️ Not solved: {result.get('error', 'unknown')}")
            return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        await page.close()
        await solver.cleanup()


async def main():
    """Run all tests"""
    print("🚀 COMPREHENSIVE REAL CAPTCHA TESTING")
    print("=" * 70)

    results = {}

    # Test each type
    results['recaptcha_v2'] = await test_recaptcha_v2()
    results['hcaptcha'] = await test_hcaptcha()
    results['turnstile'] = await test_turnstile()
    results['simple'] = await test_simple_captcha()
    results['geetest'] = await test_geetest()

    # Cleanup
    await browser_manager.close()

    # Summary
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)

    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")

    total = len(results)
    passed = sum(results.values())

    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.0f}%)")

    print("\n" + "=" * 70)

    if passed == total:
        print("✅ ALL TESTS PASSED!")
    elif passed > 0:
        print("⚠️ PARTIAL SUCCESS")
    else:
        print("❌ ALL TESTS FAILED")

    return results


if __name__ == "__main__":
    asyncio.run(main())