#!/usr/bin/env python3
"""Analyze VK challenge page in detail"""

import asyncio
import sys
import re
import json
sys.path.insert(0, '/app')

from playwright.async_api import async_playwright


async def analyze_vk_challenge():
    """Deep analysis of VK challenge page"""
    print("=" * 70)
    print("DEEP ANALYSIS OF VK CHALLENGE PAGE")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Headless for Docker
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()

        try:
            # Navigate to VK
            print("\n🌐 Loading vk.com...")
            await page.goto('https://vk.com', wait_until='networkidle', timeout=60000)
            await asyncio.sleep(3)

            url = page.url
            print(f"URL: {url}")

            # Check if challenge page
            if 'challenge' in url:
                print("✅ VK Challenge page detected")

                # Get full HTML
                html = await page.content()

                # Save HTML for analysis
                with open('vk_challenge.html', 'w', encoding='utf-8') as f:
                    f.write(html)
                print("📄 HTML saved to vk_challenge.html")

                # Parse URL parameters
                params = {}
                if '?' in url:
                    query = url.split('?')[1]
                    for param in query.split('&'):
                        if '=' in param:
                            key, value = param.split('=', 1)
                            params[key] = value

                print(f"\n📊 URL Parameters:")
                for key, value in params.items():
                    print(f"   {key}: {value[:50]}...")

                # Look for forms
                print(f"\n🔍 Forms:")
                forms = await page.locator('form').all()
                print(f"   Total forms: {len(forms)}")

                for i, form in enumerate(forms):
                    action = await form.get_attribute('action')
                    method = await form.get_attribute('method')
                    print(f"   Form {i}: action={action}, method={method}")

                    # Get inputs
                    inputs = await form.locator('input').all()
                    for inp in inputs:
                        name = await inp.get_attribute('name')
                        type_ = await inp.get_attribute('type')
                        value = await inp.get_attribute('value')
                        print(f"      input: name={name}, type={type_}, value={value}")

                # Look for buttons
                print(f"\n🔍 Buttons:")
                buttons = await page.locator('button').all()
                print(f"   Total buttons: {len(buttons)}")

                for i, btn in enumerate(buttons):
                    text = await btn.text_content()
                    btn_type = await btn.get_attribute('type')
                    onclick = await btn.get_attribute('onclick')
                    print(f"   Button {i}: '{text}', type={btn_type}, onclick={onclick}")

                # Look for JavaScript
                print(f"\n🔍 JavaScript:")
                scripts = await page.locator('script').all()
                print(f"   Total scripts: {len(scripts)}")

                # Check for specific JS functions
                js_keywords = ['challenge', 'verify', 'check', 'submit', 'validate']
                for keyword in js_keywords:
                    if keyword in html:
                        print(f"   Found '{keyword}' in HTML")

                # Look for VK ID widget
                print(f"\n🔍 VK ID Widget:")
                iframes = await page.locator('iframe').all()
                print(f"   Total iframes: {len(iframes)}")

                for i, iframe in enumerate(iframes):
                    src = await iframe.get_attribute('src')
                    print(f"   iframe {i}: {src}")

                # Check for VK ID
                vk_id_elem = await page.locator('[class*="vk-id"], [id*="vk-id"]').count()
                print(f"   VK ID elements: {vk_id_elem}")

                # Look for Cloudflare
                print(f"\n🔍 Cloudflare:")
                cf_indicators = ['cf-', 'cloudflare', 'challenge-platform']
                for indicator in cf_indicators:
                    if indicator in html:
                        print(f"   Found '{indicator}'")

                # Screenshot
                await page.screenshot(path='vk_challenge_deep.png', full_page=True)
                print("\n📸 Screenshot: vk_challenge_deep.png")

                # Try to click button
                print(f"\n🤖 Attempting to solve...")
                if len(buttons) > 0:
                    first_btn = buttons[0]
                    text = await first_btn.text_content()
                    print(f"   Clicking button: '{text}'")
                    await first_btn.click()
                    await asyncio.sleep(5)

                    new_url = page.url
                    print(f"   New URL: {new_url}")

                    if 'challenge' not in new_url:
                        print("✅ Challenge passed!")
                    else:
                        print("❌ Still on challenge page")

            else:
                print("⚠️ Not a challenge page")
                print(f"   This might be VK main page or login")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


async def main():
    await analyze_vk_challenge()


if __name__ == "__main__":
    asyncio.run(main())