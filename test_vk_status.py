#!/usr/bin/env python3
"""Test VK CAPTCHA - simplified version"""

import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager


async def test_vk_access():
    """Check if VK is accessible and what loads"""
    print("=" * 70)
    print("CHECKING VK ACCESS")
    print("=" * 70)

    page = await browser_manager.new_page()

    try:
        # Try main VK
        print("\n🌐 Trying vk.com...")
        try:
            await page.goto('https://vk.com', timeout=30000, wait_until='networkidle')
            await asyncio.sleep(2)

            url = page.url
            print(f"✅ Loaded: {url}")

            # Screenshot
            await page.screenshot(path='vk_com.png', full_page=True)
            print("📸 Screenshot: vk_com.png")

            # Check content
            content = await page.content()
            print(f"   Page size: {len(content)} bytes")

            # Check for login elements
            has_email = await page.locator('input[name="email"]').count() > 0
            has_pass = await page.locator('input[name="pass"]').count() > 0
            has_quick_login = await page.locator('.quick_login_button').count() > 0

            print(f"   Login form: email={has_email}, pass={has_pass}")
            print(f"   Quick login: {has_quick_login}")

        except Exception as e:
            print(f"❌ vk.com error: {e}")

        # Try VK ID
        print("\n🌐 Trying id.vk.com...")
        try:
            await page.goto('https://id.vk.com', timeout=30000, wait_until='networkidle')
            await asyncio.sleep(2)

            url = page.url
            print(f"✅ Loaded: {url}")

            await page.screenshot(path='vk_id.png', full_page=True)
            print("📸 Screenshot: vk_id.png")

            content = await page.content()
            print(f"   Page size: {len(content)} bytes")

        except Exception as e:
            print(f"❌ id.vk.com error: {e}")

        # Check if VK CAPTCHA test page exists
        print("\n🌐 Checking for VK CAPTCHA demo...")
        demo_sites = [
            'https://vk.com/captcha',  # Hypothetical
            'https://dev.vk.com/captcha',  # Developer docs
        ]

        for demo_url in demo_sites:
            try:
                await page.goto(demo_url, timeout=10000)
                url = page.url
                print(f"   {demo_url} → {url}")
                await page.screenshot(path=f'demo_{demo_url.split("/")[-1]}.png')
            except Exception as e:
                print(f"   {demo_url}: {str(e)[:50]}")

        print("\n" + "=" * 70)
        print("ANALYSIS")
        print("=" * 70)
        print("\n⚠️ VK требует реальный аккаунт для тестирования CAPTCHA")
        print("   Решение:")
        print("   1. Использовать реальный VK аккаунт")
        print("   2. Несколько неудачных попыток входа → CAPTCHA")
        print("   3. Или найти VK API с CAPTCHA demo")

    finally:
        await page.close()
        await browser_manager.close()


async def main():
    await test_vk_access()


if __name__ == "__main__":
    asyncio.run(main())