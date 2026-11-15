#!/usr/bin/env python3
"""Try different CAPTCHA sites and approaches"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.turnstile import TurnstileSolver
from workers.solvers.hcaptcha import HcaptchaSolver
from workers.solvers.recaptcha import RecaptchaV2Solver
from app.utils.browser import browser_manager


async def try_turnstile_extended():
    """Try Turnstile with very long wait time"""
    print("\n" + "="*70)
    print("🧪 Attempt 1: Turnstile with 120s wait")
    print("="*70)
    
    solver = TurnstileSolver()
    await solver.setup()
    
    try:
        # Modify solver to wait longer
        import time
        page = await browser_manager.new_page(stealth=True)
        
        try:
            await page.goto('https://demo.turnstile.workers.dev/', timeout=90000, wait_until='domcontentloaded')
            await page.wait_for_selector('iframe[src*="challenges.cloudflare.com"]', timeout=60000)
            
            print("⏳ Waiting 120 seconds for auto-solve...")
            await asyncio.sleep(120)
            
            # Try multiple token extraction methods
            for attempt in range(5):
                token = await page.evaluate('''
                    () => {
                        // Try different selectors
                        const selectors = [
                            'input[name="cf-turnstile-response"]',
                            '[name="cf-turnstile-response"]',
                            'input[data-testid="turnstile-response"]'
                        ];
                        
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.value && el.value.length > 10) {
                                return el.value;
                            }
                        }
                        
                        // Try to get from turnstile object
                        if (window.turnstile) {
                            try {
                                return window.turnstile.getResponse();
                            } catch (e) {}
                        }
                        
                        return null;
                    }
                ''')
                
                if token:
                    print(f"✅ Turnstile solved! Token: {token[:80]}...")
                    return True
                
                await asyncio.sleep(10)
            
            print("❌ No token after extended wait")
            return False
        finally:
            await page.close()
    except Exception as e:
        print(f"❌ Error: {str(e)[:100]}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def try_simple_recaptcha():
    """Try simpler reCAPTCHA approach"""
    print("\n" + "="*70)
    print("🧪 Attempt 2: Simple reCAPTCHA (no ML, just click)")
    print("="*70)
    
    solver = RecaptchaV2Solver()
    await solver.setup()
    
    try:
        page = await browser_manager.new_page(stealth=True)
        
        try:
            await page.goto('https://www.google.com/recaptcha/api2/demo', timeout=60000, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            
            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await checkbox_frame.locator('#recaptcha-anchor').click()
            
            # Wait longer for auto-solve
            print("⏳ Waiting 30s for potential auto-solve...")
            await asyncio.sleep(30)
            
            # Check token
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token and len(token) > 10:
                print(f"✅ Auto-solved! Token: {token[:80]}...")
                return True
            else:
                print("❌ No auto-solve, image challenge required")
                return False
        finally:
            await page.close()
    except Exception as e:
        print(f"❌ Error: {str(e)[:100]}")
        return False
    finally:
        await solver.cleanup()
        await browser_manager.close()


async def main():
    """Try different approaches"""
    print("🧪 Testing Alternative CAPTCHA Solving Approaches")
    
    attempts = [
        ("Turnstile Extended Wait", try_turnstile_extended),
        ("Simple reCAPTCHA", try_simple_recaptcha),
    ]
    
    results = {}
    for name, attempt_func in attempts:
        print(f"\n{'='*70}")
        print(f"Trying: {name}")
        print(f"{'='*70}")
        success = await attempt_func()
        results[name] = success
        
        if success:
            print(f"\n🎉 SUCCESS with {name}!")
            break
        
        await asyncio.sleep(3)
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{status}: {name}")
    
    success_count = sum(1 for v in results.values() if v)
    print(f"\nSuccess rate: {success_count}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())