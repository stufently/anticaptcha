#!/usr/bin/env python3
"""Test on multiple real CAPTCHA sites"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.recaptcha import RecaptchaV2Solver
from workers.solvers.hcaptcha import HcaptchaSolver
from workers.solvers.turnstile import TurnstileSolver
from app.utils.browser import browser_manager


async def test_recaptcha_google():
    """Test Google reCAPTCHA demo (should get COCO class)"""
    print("\n" + "="*70)
    print("🧪 TEST 1: Google reCAPTCHA Demo")
    print("="*70)
    
    solver = RecaptchaV2Solver()
    await solver.setup()
    
    try:
        result = await solver.solve({
            "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
            "page_url": "https://www.google.com/recaptcha/api2/demo"
        })
        
        if result.get('token'):
            print(f"\n✅✅✅ SUCCESS!")
            print(f"Token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n⚠️ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def test_recaptcha_alternative():
    """Test alternative reCAPTCHA site"""
    print("\n" + "="*70)
    print("🧪 TEST 2: Alternative reCAPTCHA Demo")
    print("="*70)
    
    solver = RecaptchaV2Solver()
    await solver.setup()
    
    try:
        result = await solver.solve({
            "site_key": "6LfD3sIUAAAAAOXL5Yb5_LnX4fCGngHtUZ5n-t0G",
            "page_url": "https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php"
        })
        
        if result.get('token'):
            print(f"\n✅ SUCCESS!")
            print(f"Token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n⚠️ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def test_hcaptcha():
    """Test hCaptcha"""
    print("\n" + "="*70)
    print("🧪 TEST 3: hCaptcha Demo")
    print("="*70)
    
    solver = HcaptchaSolver()
    await solver.setup()
    
    try:
        result = await solver.solve({
            "site_key": "a5f74b19-9e45-40e0-b45d-47ff91b7a6c2",
            "page_url": "https://accounts.hcaptcha.com/demo"
        })
        
        if result.get('token'):
            print(f"\n✅ SUCCESS!")
            print(f"Token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n⚠️ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def test_turnstile():
    """Test Cloudflare Turnstile"""
    print("\n" + "="*70)
    print("🧪 TEST 4: Cloudflare Turnstile")
    print("="*70)
    
    solver = TurnstileSolver()
    await solver.setup()
    
    try:
        result = await solver.solve({
            "site_key": "0x4AAAAAAASGzhKmSbZ3bF5k",
            "page_url": "https://demo.turnstile.workers.dev/"
        })
        
        if result.get('token'):
            print(f"\n✅ SUCCESS!")
            print(f"Token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n⚠️ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def main():
    """Run all tests"""
    print("\n🚀 Testing on Multiple CAPTCHA Sites")
    print("="*70)
    
    results = {}
    
    # Test each site
    results['Google reCAPTCHA'] = await test_recaptcha_google()
    results['Alternative reCAPTCHA'] = await test_recaptcha_alternative()
    results['hCaptcha'] = await test_hcaptcha()
    results['Turnstile'] = await test_turnstile()
    
    # Summary
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)
    
    success = sum(1 for v in results.values() if v)
    total = len(results)
    
    for site, result in results.items():
        status = "✅ SUCCESS" if result else "❌ FAILED"
        print(f"{status}: {site}")
    
    print(f"\n📈 Success Rate: {success}/{total} ({success/total*100:.1f}%)")
    
    print("\n" + "="*70)
    print("💡 NOTES")
    print("="*70)
    print("• reCAPTCHA success depends on challenge type (COCO classes work)")
    print("• hCaptcha and Turnstile usually auto-solve")
    print("• For reCAPTCHA-specific classes, train custom Yolo model")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())