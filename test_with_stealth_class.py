#!/usr/bin/env python3
"""Test with Stealth class"""
import asyncio
import sys
sys.path.insert(0, '/app')

from playwright.async_api import async_playwright
from playwright_stealth import Stealth


async def test_recaptcha():
    """Test reCAPTCHA with Stealth"""
    print("🔍 Testing reCAPTCHA with Stealth\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        page = await browser.new_page()
        
        # Apply stealth
        print("1️⃣ Applying stealth...")
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
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
        iframes = await page.query_selector_all('iframe')
        print(f"   Iframes: {len(iframes)}")
        
        recaptcha_found = False
        for iframe in iframes:
            src = await iframe.get_attribute('src')
            if src and 'recaptcha' in src:
                print(f"   ✅ reCAPTCHA: {src[:80]}")
                recaptcha_found = True
        
        if recaptcha_found:
            print("\n3️⃣ Clicking checkbox...")
            frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await frame.locator('#recaptcha-anchor').click()
            print("   ✅ Clicked\n")
            
            await asyncio.sleep(5)
            
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token:
                print(f"✅✅✅ SUCCESS!\n")
                print(f"Token: {token[:80]}...")
            else:
                print("⚠️ No token")
        else:
            print("\n⚠️ No reCAPTCHA found")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_recaptcha())