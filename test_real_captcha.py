#!/usr/bin/env python3
"""Test CAPTCHA solving on real websites"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager


async def test_recaptcha_demo():
    """Test reCAPTCHA v2 on Google demo page"""
    print("🔍 Testing Google reCAPTCHA demo...")
    
    page = await browser_manager.new_page()
    
    try:
        # Navigate to reCAPTCHA demo
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000
        )
        print("✅ Page loaded")
        
        # Get site key
        site_key = await page.evaluate('''
            () => {
                const iframe = document.querySelector('iframe[src*="recaptcha"]');
                if (!iframe) return null;
                const src = iframe.getAttribute('src');
                const match = src.match(/[?&]k=([^&]+)/);
                return match ? match[1] : null;
            }
        ''')
        print(f"🔑 Site key: {site_key}")
        
        # Find reCAPTCHA iframe
        await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=10000)
        print("✅ reCAPTCHA iframe found")
        
        # Click checkbox
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('.recaptcha-checkbox').click()
        print("✅ Checkbox clicked")
        
        # Wait for response
        await asyncio.sleep(5)
        
        # Try to get token
        token = await page.evaluate('''
            () => {
                return document.getElementById('g-recaptcha-response')?.value;
            }
        ''')
        
        if token:
            print(f"✅ Token received: {token[:50]}...")
            return {"token": token}
        else:
            print("⚠️ No token yet - may need to solve image challenge")
            
            # Check if challenge appeared
            try:
                challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
                await challenge_frame.wait_for_selector('.rc-imageselect', timeout=2000)
                print("⚠️ Image challenge detected - requires ML model")
                return {"status": "challenge_required", "type": "image_select"}
            except:
                print("⚠️ No challenge detected but no token")
                return {"status": "no_token"}
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}
    
    finally:
        await page.close()


async def test_turnstile_site():
    """Test Turnstile on a real website"""
    print("\n🔍 Testing Turnstile on community.topazlabs.com...")
    
    page = await browser_manager.new_page()
    
    try:
        # Try a site known to use Turnstile
        await page.goto(
            'https://community.topazlabs.com/',
            timeout=60000,
            wait_until='domcontentloaded'
        )
        print("✅ Page loaded")
        
        # Look for Turnstile widget
        try:
            await page.wait_for_selector('iframe[src*="challenges.cloudflare.com"]', timeout=10000)
            print("✅ Turnstile iframe found")
            
            # Wait for auto-solve
            await asyncio.sleep(5)
            
            # Try to get token
            token = await page.evaluate('''
                () => {
                    return document.querySelector('input[name="cf-turnstile-response"]')?.value;
                }
            ''')
            
            if token:
                print(f"✅ Turnstile token: {token[:50]}...")
                return {"token": token}
            else:
                print("⚠️ No token received")
                return {"status": "no_token"}
        
        except Exception as e:
            print(f"⚠️ Turnstile not found or error: {e}")
            return {"status": "no_turnstile"}
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}
    
    finally:
        await page.close()


async def test_simple_captcha_site():
    """Test on a site with simple text CAPTCHA"""
    print("\n🔍 Looking for sites with simple CAPTCHA...")
    
    # Try to find a demo site with simple CAPTCHA
    page = await browser_manager.new_page()
    
    try:
        # Example: PHP captcha demo
        await page.goto(
            'https://www.phpcaptcha.org/try-securimage/',
            timeout=60000
        )
        print("✅ Page loaded")
        
        # Check for CAPTCHA image
        captcha_img = await page.query_selector('img[src*="securimage"]')
        if captcha_img:
            print("✅ Simple CAPTCHA image found")
            
            # Take screenshot
            screenshot = await captcha_img.screenshot()
            print(f"📸 CAPTCHA image captured ({len(screenshot)} bytes)")
            
            # Note: Would need OCR to solve this
            return {"status": "image_captured", "image_size": len(screenshot)}
        else:
            print("⚠️ No CAPTCHA image found")
            return {"status": "no_captcha"}
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}
    
    finally:
        await page.close()


async def main():
    """Run all tests"""
    print("🚀 Starting real CAPTCHA tests...\n")
    
    results = {}
    
    # Test reCAPTCHA
    results['recaptcha'] = await test_recaptcha_demo()
    
    # Test Turnstile
    results['turnstile'] = await test_turnstile_site()
    
    # Test simple CAPTCHA
    results['simple'] = await test_simple_captcha_site()
    
    # Cleanup
    await browser_manager.close()
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    for test_name, result in results.items():
        print(f"\n{test_name.upper()}:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())