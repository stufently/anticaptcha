#!/usr/bin/env python3
"""Test on multiple reCAPTCHA demo sites"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.recaptcha import RecaptchaV2Solver
from app.utils.browser import browser_manager


# List of reCAPTCHA demo/test sites
RECAPTCHA_SITES = [
    {
        "name": "Google Official Demo",
        "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
        "page_url": "https://www.google.com/recaptcha/api2/demo"
    },
    {
        "name": "AppSpot Demo 1",
        "site_key": "6LfD3sIUAAAAAOXL5Yb5_LnX4fCGngHtUZ5n-t0G",
        "page_url": "https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php"
    },
    {
        "name": "AppSpot Demo 2",
        "site_key": "6Ld2sf4SAAAAAKLXMH0I9NlonX6y4x6oSBnpFreO",
        "page_url": "https://recaptcha-demo.appspot.com/recaptcha-v2-invisible.php"
    },
    {
        "name": "2Captcha Demo",
        "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
        "page_url": "https://2captcha.com/demo/recaptcha-v2"
    }
]


async def test_site(site):
    """Test a single site"""
    print(f"\n{'='*70}")
    print(f"Testing: {site['name']}")
    print(f"{'='*70}")
    
    solver = RecaptchaV2Solver()
    await solver.setup()
    
    try:
        result = await solver.solve({
            "site_key": site["site_key"],
            "page_url": site["page_url"]
        })
        
        if result.get('token'):
            print(f"\n✅✅✅ SUCCESS! Token: {result['token'][:80]}...")
            return True
        else:
            print(f"\n❌ No token")
            return False
    except Exception as e:
        print(f"\n❌ Error: {str(e)[:100]}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def main():
    """Test all sites"""
    print("🧪 Testing Multiple reCAPTCHA Demo Sites")
    print(f"Total sites: {len(RECAPTCHA_SITES)}")
    
    results = {}
    for site in RECAPTCHA_SITES:
        success = await test_site(site)
        results[site['name']] = success
        
        if success:
            print(f"\n🎉 Found working site: {site['name']}")
            break  # Stop on first success
        
        # Brief pause between tests
        await asyncio.sleep(2)
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{status}: {name}")
    
    success_count = sum(1 for v in results.values() if v)
    print(f"\nSuccess rate: {success_count}/{len(results)}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())