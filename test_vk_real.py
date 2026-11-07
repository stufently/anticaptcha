#!/usr/bin/env python3
"""Test VK CAPTCHA solver on real VK website"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from workers.solvers.vk import VKCaptchaSolver
from workers.classifiers.yolo import HybridClassifier


async def test_vk_captcha():
    """Test VK CAPTCHA on real VK login page"""
    print("=" * 70)
    print("TESTING VK CAPTCHA SOLVER ON REAL VK WEBSITE")
    print("=" * 70)

    # Initialize solver with hybrid classifier
    solver = VKCaptchaSolver()
    solver.vision_classifier = HybridClassifier()

    page = await browser_manager.new_page()

    try:
        # Navigate to VK login page (triggers CAPTCHA after failed attempts)
        print("\n🌐 Navigating to VK login page...")
        await page.goto('https://vk.com', timeout=60000, wait_until='domcontentloaded')
        print("✅ VK loaded")

        # Take screenshot
        await page.screenshot(path='vk_homepage.png')
        print("📸 Screenshot saved: vk_homepage.png")

        # Check what's on page
        title = await page.title()
        print(f"   Page title: {title}")

        url = page.url
        print(f"   Current URL: {url}")

        # Check if blocked
        content = await page.content()
        if "blocked" in content.lower() or "доступ" in content.lower():
            print("⚠️ VK may be blocked in this region or for this IP")

        # Check page structure
        print("\n🔍 Checking page structure...")

        # VK login form selectors
        selectors = {
            "email_input": 'input[name="email"], input[type="text"]',
            "pass_input": 'input[name="pass"], input[type="password"]',
            "login_button": 'button[type="submit"], .login_button',
            "quick_login": '.quick_login_button, [onclick*="login"]',
        }

        for name, selector in selectors.items():
            count = await page.locator(selector).count()
            print(f"   {name}: {count} found")

        # Try alternative login URL
        if await page.locator(selectors["email_input"]).count() == 0:
            print("\n🔄 Trying alternative login URL...")
            await page.goto('https://id.vk.com/auth', timeout=60000)
            await page.screenshot(path='vk_auth.png')
            print("📸 Screenshot saved: vk_auth.png")

            url = page.url
            print(f"   Current URL: {url}")

            # Recheck for login form
            for name, selector in selectors.items():
                count = await page.locator(selector).count()
                print(f"   {name}: {count} found")

        # Check if already logged in
        if await page.locator('#top_profile_link').count() > 0:
            print("⚠️ Already logged in, logout first")
            # Would need to logout
            return {"status": "already_logged_in"}

        # Try to trigger CAPTCHA by attempting login
        print("\n🔍 Attempting to trigger CAPTCHA...")

        # Enter wrong credentials to trigger CAPTCHA
        email_input = page.locator('input[name="email"]')
        pass_input = page.locator('input[name="pass"]')

        if await email_input.count() > 0:
            await email_input.fill("test@test.com")
            await pass_input.fill("wrongpassword")

            # Click login button
            login_button = page.locator('button[type="submit"]')
            if await login_button.count() > 0:
                await login_button.click()

            # Wait for response
            await asyncio.sleep(3)

            # Check for CAPTCHA
            print("\n🔍 Checking for VK CAPTCHA...")

            is_captcha = await solver.detect(page)

            if is_captcha:
                print("✅ VK CAPTCHA detected!")

                # Detect type
                captcha_type = await solver._detect_captcha_type(page)
                print(f"   Type: {captcha_type}")

                # Try to solve
                print("\n🤖 Attempting to solve...")
                success = await solver.solve(page, None)

                if success:
                    print("✅ VK CAPTCHA SOLVED!")
                    return {"status": "solved", "type": captcha_type}
                else:
                    print("❌ Failed to solve")
                    return {"status": "failed", "type": captcha_type}
            else:
                print("⚠️ No CAPTCHA detected")
                print("   VK may not show CAPTCHA on first attempt")
                print("   Or may require more login attempts")

                # Check page content
                content = await page.content()
                if "captcha" in content.lower():
                    print("   Found 'captcha' in page HTML")

                # Take screenshot for debugging
                await page.screenshot(path='vk_page.png')
                print("   Screenshot saved: vk_page.png")

                return {"status": "no_captcha"}
        else:
            print("⚠️ Login form not found")
            return {"status": "no_login_form"}

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}

    finally:
        await page.close()
        await browser_manager.close()
        solver.vision_classifier.cleanup()


async def main():
    """Run VK CAPTCHA test"""
    result = await test_vk_captcha()

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())