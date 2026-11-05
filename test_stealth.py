#!/usr/bin/env python3
"""Test reCAPTCHA solving with stealth capabilities"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from app.utils.stealth import StealthConfig


async def test_stealth_recaptcha():
    """Test reCAPTCHA with stealth configuration"""
    print("🚀 Testing reCAPTCHA with Stealth Configuration\n")
    
    # Create stealth page
    page = await browser_manager.new_page(stealth=True)
    
    try:
        # Navigate with human-like delay
        print("1️⃣ Navigating to Google reCAPTCHA demo...")
        await StealthConfig.human_delay(0.5, 1.0)
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='domcontentloaded'
        )
        print("   ✅ Page loaded\n")
        
        # Simulate human behavior
        print("2️⃣ Simulating human behavior...")
        await StealthConfig.random_mouse_movements(page, num_moves=3)
        print("   ✅ Random mouse movements\n")
        
        # Wait for reCAPTCHA
        print("3️⃣ Waiting for reCAPTCHA widget...")
        await StealthConfig.human_delay(1.0, 2.0)
        await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=15000)
        print("   ✅ reCAPTCHA found\n")
        
        # Human-like click
        print("4️⃣ Clicking checkbox with human-like behavior...")
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await StealthConfig.human_delay(0.5, 1.0)
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Checkbox clicked\n")
        
        # Wait for result
        print("5️⃣ Waiting for result...")
        await StealthConfig.human_delay(3.0, 5.0)
        
        # Check for challenge
        try:
            challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
            await challenge_frame.wait_for_selector('.rc-imageselect', timeout=3000)
            
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"   ⚠️ Image challenge appeared: {instruction[:50]}...\n")
            
            return {
                "success": False,
                "reason": "challenge",
                "instruction": instruction
            }
        
        except:
            # Check for token
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token and len(token) > 10:
                print(f"   ✅✅✅ SUCCESS! Token received!\n")
                print(f"   Token: {token[:80]}...\n")
                return {"success": True, "token": token}
            else:
                print("   ⚠️ No token received\n")
                return {"success": False, "reason": "no_token"}
    
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return {"success": False, "error": str(e)}
    
    finally:
        print("6️⃣ Cleanup...")
        await page.close()
        await browser_manager.close()
        print("   ✅ Done\n")


async def test_bot_detection():
    """Test if site detects automation"""
    print("\n🔍 Testing Bot Detection...\n")
    
    # Test without stealth
    print("A) Testing WITHOUT stealth:")
    page_normal = await browser_manager.new_page(stealth=False)
    
    try:
        await page_normal.goto('https://bot.sannysoft.com/', timeout=30000)
        await asyncio.sleep(5)
        
        # Check detection results
        webdriver_result = await page_normal.evaluate('() => navigator.webdriver')
        print(f"   navigator.webdriver: {webdriver_result}")
        
        await page_normal.close()
    
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test with stealth
    print("\nB) Testing WITH stealth:")
    page_stealth = await browser_manager.new_page(stealth=True)
    
    try:
        await page_stealth.goto('https://bot.sannysoft.com/', timeout=30000)
        await asyncio.sleep(5)
        
        # Check detection results
        webdriver_result = await page_stealth.evaluate('() => navigator.webdriver')
        print(f"   navigator.webdriver: {webdriver_result}")
        
        # Take screenshot
        await page_stealth.screenshot(path='/tmp/stealth_test.png')
        print("   📸 Screenshot saved: /tmp/stealth_test.png")
        
        await page_stealth.close()
    
    except Exception as e:
        print(f"   Error: {e}")
    
    await browser_manager.close()


async def main():
    """Run all stealth tests"""
    print("="*60)
    print("STEALTH & HUMAN BEHAVIOR TEST")
    print("="*60)
    
    # Test bot detection
    await test_bot_detection()
    
    # Test reCAPTCHA
    result = await test_stealth_recaptcha()
    
    # Summary
    print("="*60)
    print("📊 SUMMARY")
    print("="*60)
    
    if result.get('success'):
        print("\n✅ reCAPTCHA solved successfully with stealth!")
    elif result.get('reason') == 'challenge':
        print("\n✅ Stealth working - reCAPTCHA shows real challenge")
        print(f"   Challenge: {result.get('instruction', 'unknown')}")
    else:
        print(f"\n⚠️ Result: {result.get('reason', result.get('error'))}")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())