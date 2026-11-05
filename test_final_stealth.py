#!/usr/bin/env python3
"""Test with playwright-stealth package (correct API)"""
import asyncio
import sys
sys.path.insert(0, '/app')

from playwright.async_api import async_playwright
from playwright_stealth import stealth_sync


async def test_with_stealth():
    """Test using playwright-stealth"""
    print("🔍 Testing reCAPTCHA with playwright-stealth\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        page = await browser.new_page()
        
        # Apply stealth (sync wrapper for async)
        print("1️⃣ Applying stealth...")
        await page.goto('about:blank')
        stealth_sync(page)
        print("   ✅ Applied\n")
        
        # Test reCAPTCHA
        print("2️⃣ Loading Google reCAPTCHA demo...")
        try:
            response = await page.goto(
                'https://www.google.com/recaptcha/api2/demo',
                timeout=60000,
                wait_until='domcontentloaded'
            )
            print(f"   ✅ Status: {response.status}\n")
            
            # Check content
            await asyncio.sleep(3)
            content = await page.content()
            print(f"   Page size: {len(content)} bytes")
            
            # Find iframes
            iframes = await page.query_selector_all('iframe')
            print(f"   Iframes: {len(iframes)}\n")
            
            for i, iframe in enumerate(iframes):
                src = await iframe.get_attribute('src')
                if src:
                    print(f"   {i+1}. {src[:100]}")
            
            # Try reCAPTCHA
            recaptcha = await page.query_selector('iframe[src*="recaptcha"]')
            if recaptcha:
                print("\n✅ reCAPTCHA found!\n")
                
                print("3️⃣ Clicking checkbox...")
                frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
                await frame.locator('#recaptcha-anchor').click()
                print("   ✅ Clicked\n")
                
                await asyncio.sleep(5)
                
                token = await page.evaluate('''
                    () => document.getElementById('g-recaptcha-response')?.value
                ''')
                
                if token:
                    print(f"✅ TOKEN: {token[:50]}...")
                else:
                    print("⚠️ No token - checking challenge...")
                    try:
                        challenge = page.frame_locator('iframe[src*="bframe"]')
                        await challenge.wait_for_selector('.rc-imageselect', timeout=3000)
                        instruction = await challenge.locator('.rc-imageselect-instructions').text_content()
                        print(f"   Challenge: {instruction}")
                    except:
                        print("   No challenge visible")
            else:
                print("\n⚠️ No reCAPTCHA iframe")
                await page.screenshot(path='/tmp/debug.png')
                print("📸 Screenshot: /tmp/debug.png")
        
        except Exception as e:
            print(f"❌ Error: {e}")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_with_stealth())