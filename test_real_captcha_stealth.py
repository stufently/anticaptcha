#!/usr/bin/env python3
"""Test real CAPTCHA solving with stealth on multiple sites"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from app.utils.stealth import StealthConfig


async def test_recaptcha_google():
    """Test Google reCAPTCHA demo with stealth"""
    print("\n" + "="*60)
    print("🔍 Testing Google reCAPTCHA Demo")
    print("="*60)
    
    page = await browser_manager.new_page(stealth=True)
    
    try:
        print("1️⃣ Loading page...")
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Loaded")
        
        # Human behavior
        await StealthConfig.random_mouse_movements(page, num_moves=2)
        await StealthConfig.human_delay(1.0, 2.0)
        
        # Wait for reCAPTCHA
        print("2️⃣ Finding reCAPTCHA widget...")
        await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=30000)
        print("   ✅ Found")
        
        # Click checkbox
        print("3️⃣ Clicking checkbox...")
        await StealthConfig.human_delay(0.5, 1.0)
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Clicked")
        
        # Wait for result
        print("4️⃣ Waiting for result...")
        await StealthConfig.human_delay(3.0, 5.0)
        
        # Check for challenge or token
        try:
            challenge_frame = page.frame_locator('iframe[src*="bframe"]')
            await challenge_frame.wait_for_selector('.rc-imageselect', timeout=5000)
            
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"   ⚠️ Challenge: {instruction[:60]}")
            
            # Get challenge images
            images = await challenge_frame.locator('.rc-image-tile-wrapper').all()
            print(f"   📸 {len(images)} images")
            
            return {
                "site": "Google reCAPTCHA",
                "success": False,
                "reason": "challenge",
                "instruction": instruction
            }
        
        except:
            # Check token
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token:
                print(f"   ✅ Token: {token[:50]}...")
                return {
                    "site": "Google reCAPTCHA",
                    "success": True,
                    "token": token
                }
            else:
                print("   ⚠️ No token")
                return {
                    "site": "Google reCAPTCHA",
                    "success": False,
                    "reason": "no_token"
                }
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"site": "Google reCAPTCHA", "error": str(e)}
    
    finally:
        await page.close()


async def test_recaptcha_alternative():
    """Test alternative reCAPTCHA demo"""
    print("\n" + "="*60)
    print("🔍 Testing Alternative reCAPTCHA Demo")
    print("="*60)
    
    page = await browser_manager.new_page(stealth=True)
    
    try:
        print("1️⃣ Loading page...")
        await page.goto(
            'https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Loaded")
        
        await StealthConfig.human_delay(1.0, 2.0)
        
        print("2️⃣ Finding reCAPTCHA...")
        await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=30000)
        print("   ✅ Found")
        
        print("3️⃣ Clicking checkbox...")
        await StealthConfig.human_delay(0.5, 1.0)
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Clicked")
        
        print("4️⃣ Waiting...")
        await StealthConfig.human_delay(5.0, 8.0)
        
        # Check result
        try:
            challenge_frame = page.frame_locator('iframe[src*="bframe"]')
            await challenge_frame.wait_for_selector('.rc-imageselect', timeout=5000)
            
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"   ⚠️ Challenge: {instruction[:60]}")
            
            return {
                "site": "Alternative reCAPTCHA",
                "success": False,
                "reason": "challenge",
                "instruction": instruction
            }
        
        except:
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token:
                print(f"   ✅ Token: {token[:50]}...")
                return {
                    "site": "Alternative reCAPTCHA",
                    "success": True,
                    "token": token
                }
            else:
                print("   ⚠️ No token")
                return {
                    "site": "Alternative reCAPTCHA",
                    "success": False,
                    "reason": "no_token"
                }
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"site": "Alternative reCAPTCHA", "error": str(e)}
    
    finally:
        await page.close()


async def test_hcaptcha_demo():
    """Test hCaptcha demo"""
    print("\n" + "="*60)
    print("🔍 Testing hCaptcha Demo")
    print("="*60)
    
    page = await browser_manager.new_page(stealth=True)
    
    try:
        print("1️⃣ Loading page...")
        await page.goto(
            'https://accounts.hcaptcha.com/demo',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Loaded")
        
        await StealthConfig.human_delay(2.0, 3.0)
        
        print("2️⃣ Finding hCaptcha...")
        await page.wait_for_selector('iframe[src*="hcaptcha"]', timeout=30000)
        print("   ✅ Found")
        
        print("3️⃣ Clicking checkbox...")
        await StealthConfig.human_delay(0.5, 1.0)
        
        hcap_frame = page.frame_locator('iframe[src*="hcaptcha"]')
        await hcap_frame.locator('.checkbox').click()
        print("   ✅ Clicked")
        
        print("4️⃣ Waiting...")
        await StealthConfig.human_delay(5.0, 8.0)
        
        # Check for token
        token = await page.evaluate('''
            () => document.querySelector('input[name="h-captcha-response"]')?.value
        ''')
        
        if token:
            print(f"   ✅ Token: {token[:50]}...")
            return {
                "site": "hCaptcha",
                "success": True,
                "token": token
            }
        else:
            print("   ⚠️ No token - may need challenge solving")
            return {
                "site": "hCaptcha",
                "success": False,
                "reason": "challenge"
            }
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"site": "hCaptcha", "error": str(e)}
    
    finally:
        await page.close()


async def test_turnstile_demo():
    """Test Cloudflare Turnstile demo"""
    print("\n" + "="*60)
    print("🔍 Testing Cloudflare Turnstile Demo")
    print("="*60)
    
    page = await browser_manager.new_page(stealth=True)
    
    try:
        print("1️⃣ Loading page...")
        await page.goto(
            'https://demo.turnstile.workers.dev/',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Loaded")
        
        await StealthConfig.human_delay(2.0, 3.0)
        
        print("2️⃣ Finding Turnstile...")
        await page.wait_for_selector('iframe[src*="challenges.cloudflare.com"]', timeout=30000)
        print("   ✅ Found")
        
        print("3️⃣ Waiting for auto-solve...")
        await StealthConfig.human_delay(5.0, 8.0)
        
        # Check for token
        token = await page.evaluate('''
            () => {
                return document.querySelector('input[name="cf-turnstile-response"]')?.value ||
                       window.turnstile?.getResponse();
            }
        ''')
        
        if token:
            print(f"   ✅ Token: {token[:50]}...")
            return {
                "site": "Turnstile",
                "success": True,
                "token": token
            }
        else:
            print("   ⚠️ No token")
            return {
                "site": "Turnstile",
                "success": False,
                "reason": "no_token"
            }
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"site": "Turnstile", "error": str(e)}
    
    finally:
        await page.close()


async def main():
    """Test all real CAPTCHA sites"""
    print("\n🚀 Testing Real CAPTCHA Sites with Stealth Configuration")
    print("="*60)
    
    results = []
    
    # Test each site
    results.append(await test_recaptcha_google())
    await browser_manager.close()
    
    results.append(await test_recaptcha_alternative())
    await browser_manager.close()
    
    results.append(await test_hcaptcha_demo())
    await browser_manager.close()
    
    results.append(await test_turnstile_demo())
    
    # Summary
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)
    
    solved = [r for r in results if r.get('success')]
    challenges = [r for r in results if r.get('reason') == 'challenge']
    errors = [r for r in results if r.get('error')]
    
    print(f"\n✅ Solved: {len(solved)}")
    for r in solved:
        print(f"   - {r['site']}")
    
    print(f"\n⚠️ Challenges (need ML): {len(challenges)}")
    for r in challenges:
        print(f"   - {r['site']}: {r.get('instruction', 'unknown')[:50]}")
    
    print(f"\n❌ Errors: {len(errors)}")
    for r in errors:
        print(f"   - {r['site']}: {r.get('error', 'unknown')[:50]}")
    
    print(f"\n📈 Success Rate: {len(solved)}/{len(results)} ({len(solved)/len(results)*100:.1f}%)")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())