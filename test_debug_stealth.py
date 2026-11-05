#!/usr/bin/env python3
"""Test with playwright-stealth package and debug"""
import asyncio
import sys
sys.path.insert(0, '/app')

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


async def test_with_stealth_package():
    """Test using playwright-stealth package directly"""
    print("🔍 Testing with playwright-stealth package\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        page = await browser.new_page()
        
        # Apply stealth
        print("1️⃣ Applying stealth...")
        await stealth_async(page)
        print("   ✅ Stealth applied\n")
        
        # Test Google reCAPTCHA
        print("2️⃣ Loading Google reCAPTCHA demo...")
        try:
            response = await page.goto(
                'https://www.google.com/recaptcha/api2/demo',
                timeout=60000,
                wait_until='networkidle'
            )
            print(f"   ✅ Loaded (status: {response.status})\n")
            
            # Check page content
            content = await page.content()
            print(f"   Page size: {len(content)} bytes")
            
            # Check for reCAPTCHA in HTML
            if 'recaptcha' in content.lower():
                print("   ✅ reCAPTCHA found in HTML\n")
            else:
                print("   ⚠️ No reCAPTCHA in HTML\n")
            
            # Wait and check for iframe
            print("3️⃣ Waiting for iframe...")
            await asyncio.sleep(5)
            
            # Check all iframes
            iframes = await page.query_selector_all('iframe')
            print(f"   Found {len(iframes)} iframes")
            
            for i, iframe in enumerate(iframes):
                src = await iframe.get_attribute('src')
                if src:
                    print(f"   {i+1}. {src[:80]}")
            
            # Try to find reCAPTCHA
            recaptcha_iframe = await page.query_selector('iframe[src*="recaptcha"]')
            if recaptcha_iframe:
                print("\n   ✅ reCAPTCHA iframe found!\n")
                
                # Click
                print("4️⃣ Clicking checkbox...")
                frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
                await frame.locator('#recaptcha-anchor').click()
                print("   ✅ Clicked\n")
                
                await asyncio.sleep(5)
                
                # Check result
                token = await page.evaluate('''
                    () => document.getElementById('g-recaptcha-response')?.value
                ''')
                
                if token:
                    print(f"✅ SUCCESS! Token: {token[:50]}...")
                    return {"success": True, "token": token}
                else:
                    print("⚠️ No token yet - checking for challenge")
                    return {"success": False, "reason": "no_token"}
            else:
                print("\n   ⚠️ No reCAPTCHA iframe found")
                print("   💡 Possible reasons:")
                print("      - JavaScript blocked")
                print("      - Bot detection at network level")
                print("      - IP blocked")
                
                # Take screenshot
                await page.screenshot(path='/tmp/recaptcha_debug.png')
                print("\n   📸 Screenshot saved: /tmp/recaptcha_debug.png")
                
                return {"success": False, "reason": "no_iframe"}
        
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return {"success": False, "error": str(e)}
        
        finally:
            await browser.close()


async def test_simple_site():
    """Test on a simple site without CAPTCHA to verify browser works"""
    print("\n🔍 Testing browser on simple site (example.com)...\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await stealth_async(page)
        
        await page.goto('https://example.com', timeout=30000)
        title = await page.title()
        
        print(f"   ✅ Browser works! Title: {title}\n")
        
        await browser.close()
        return True


async def main():
    """Run tests"""
    print("🚀 Debug Test with playwright-stealth")
    print("="*60)
    
    # Test browser works
    await test_simple_site()
    
    # Test reCAPTCHA
    result = await test_with_stealth_package()
    
    print("\n" + "="*60)
    print("📊 RESULT")
    print("="*60)
    
    if result.get('success'):
        print(f"\n✅ reCAPTCHA solved!")
    else:
        print(f"\n⚠️ {result.get('reason', result.get('error'))}")


if __name__ == "__main__":
    asyncio.run(main())