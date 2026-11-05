#!/usr/bin/env python3
"""Test with playwright-stealth (correct API)"""
import asyncio
import sys
sys.path.insert(0, '/app')

from playwright.async_api import async_playwright
from playwright_stealth import stealth


async def test_recaptcha_stealth():
    """Test reCAPTCHA with stealth"""
    print("🔍 Testing reCAPTCHA with stealth\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
        )
        
        page = await browser.new_page()
        
        # Apply stealth
        print("1️⃣ Applying stealth...")
        await stealth(page)
        print("   ✅ Applied\n")
        
        # Load page
        print("2️⃣ Loading reCAPTCHA demo...")
        response = await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='domcontentloaded'
        )
        print(f"   ✅ Status: {response.status}\n")
        
        await asyncio.sleep(5)
        
        # Check page
        content = await page.content()
        print(f"   Page size: {len(content)} bytes")
        
        # Find iframes
        iframes = await page.query_selector_all('iframe')
        print(f"   Iframes: {len(iframes)}")
        
        for iframe in iframes:
            src = await iframe.get_attribute('src')
            if src and 'recaptcha' in src:
                print(f"   ✅ reCAPTCHA: {src[:100]}")
        
        # Try to interact
        recaptcha_iframe = await page.query_selector('iframe[src*="recaptcha"]')
        
        if recaptcha_iframe:
            print("\n3️⃣ Clicking checkbox...")
            frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await frame.locator('#recaptcha-anchor').click()
            print("   ✅ Clicked\n")
            
            await asyncio.sleep(5)
            
            # Check token
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token:
                print(f"✅✅✅ SUCCESS! Token: {token[:60]}...")
            else:
                print("⚠️ No token - checking challenge...")
                try:
                    challenge = page.frame_locator('iframe[src*="bframe"]')
                    text = await challenge.locator('.rc-imageselect-instructions').text_content()
                    print(f"   Challenge: {text}")
                except:
                    print("   No challenge found")
        else:
            print("\n⚠️ No reCAPTCHA iframe - site may be blocking")
            await page.screenshot(path='/tmp/no_recaptcha.png')
            print("📸 Screenshot: /tmp/no_recaptcha.png")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_recaptcha_stealth())