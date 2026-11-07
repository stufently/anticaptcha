#!/usr/bin/env python3
"""Analyze VK challenge page"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager


async def analyze_challenge():
    """Analyze VK challenge page"""
    print("=" * 70)
    print("ANALYZING VK CHALLENGE PAGE")
    print("=" * 70)

    page = await browser_manager.new_page()

    try:
        # Go to VK
        await page.goto('https://vk.com', timeout=30000, wait_until='networkidle')
        await asyncio.sleep(2)

        url = page.url
        print(f"\n✅ URL: {url}")

        if 'challenge' in url:
            print("✅ VK Challenge page detected!")

            # Get page content
            content = await page.content()
            print(f"\n📄 Page size: {len(content)} bytes")

            # Look for CAPTCHA elements
            print("\n🔍 Checking for CAPTCHA elements...")

            # Check selectors from VKCaptchaSolver
            selectors = {
                "captcha_img": 'img[src*="captcha"]',
                "captcha_img_class": '.captcha_img',
                "captcha_input": 'input[name="captcha_key"]',
                "captcha_puzzle": '.captcha_puzzle',
                "captcha_slider": '.captcha_slider',
                "text_input": 'input[type="text"]',
                "button": 'button',
            }

            for name, selector in selectors.items():
                count = await page.locator(selector).count()
                if count > 0:
                    print(f"   ✅ {name}: {count} found")

                    # If it's image, get src
                    if 'img' in selector and count > 0:
                        img = page.locator(selector).first
                        src = await img.get_attribute('src')
                        if src:
                            print(f"      src: {src[:50]}...")
                else:
                    print(f"   ❌ {name}: 0 found")

            # Screenshot
            await page.screenshot(path='vk_challenge_analyzed.png', full_page=True)
            print(f"\n📸 Screenshot: vk_challenge_analyzed.png")

            # Check if VKCaptchaSolver can detect it
            from workers.solvers.vk import VKCaptchaSolver
            solver = VKCaptchaSolver()

            is_captcha = await solver.detect(page)
            print(f"\n🤖 VKCaptchaSolver.detect(): {is_captcha}")

            if is_captcha:
                captcha_type = await solver._detect_captcha_type(page)
                print(f"   Type: {captcha_type}")

                # Try to solve
                print("\n🔄 Attempting to solve...")
                solver.vision_classifier = None  # Would need real classifier

                # Don't actually solve, just show it detected
                print("   ⚠️ Solver ready, but no vision classifier configured")
                print("   Would need: HybridClassifier with qw2 CLI")

        else:
            print("⚠️ Not a challenge page")
            print("   VK may be allowing access from this IP")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await page.close()
        await browser_manager.close()


async def main():
    await analyze_challenge()


if __name__ == "__main__":
    asyncio.run(main())