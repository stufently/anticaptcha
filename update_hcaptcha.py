#!/usr/bin/env python3
"""Update hCaptcha solver to wait longer for auto-solve"""

with open('/home/deploy/github/anticaptcha/workers/solvers/hcaptcha.py', 'r') as f:
    content = f.read()

# Find and replace the solve method
old_solve = '''        page = await browser_manager.new_page(stealth=True)

        try:
            # Navigate to page
            await page.goto(page_url, timeout=settings.browser_timeout * 1000)

            # Wait for hCaptcha iframe
            await page.wait_for_selector('iframe[src*="hcaptcha"]', timeout=10000)

            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[src*="hcaptcha"]')
            await checkbox_frame.locator('.checkbox').click()

            # Wait for challenge
            await asyncio.sleep(1)

            # Try to extract token
            token = await self._extract_token(page)

            if not token:
                # Image challenge - needs ML model
                raise NotImplementedError(
                    "hCaptcha image challenge requires ML models. "
                    "Please ensure Yolo model is trained and available."
                )

            return {"token": token}

        finally:
            await page.close()'''

new_solve = '''        page = await browser_manager.new_page(stealth=True)

        try:
            # Navigate to page
            await page.goto(page_url, timeout=60000, wait_until='domcontentloaded')
            
            # Wait for hCaptcha iframe
            await page.wait_for_selector('iframe[src*="hcaptcha"]', timeout=30000)

            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[src*="hcaptcha"]')
            await checkbox_frame.locator('.checkbox').click()

            # Wait longer for potential auto-solve
            print("⏳ Waiting for hCaptcha response...")
            for i in range(15):  # Wait up to 15 seconds
                await asyncio.sleep(1)
                # Check if we got a token (auto-solved)
                token = await self._extract_token(page)
                if token:
                    print(f"✅ hCaptcha auto-solved after {i+1} seconds!")
                    return {"token": token}

            # If no token, check for challenge
            try:
                challenge_frame = page.frame_locator('iframe[src*="hcaptcha"][data-hcaptcha-widget]')
                challenge_visible = await challenge_frame.locator('.challenge-container').count()
                if challenge_visible > 0:
                    print("⚠️ hCaptcha challenge detected (needs solving)")
                    # Try waiting more for auto-solve
                    for i in range(10):
                        await asyncio.sleep(1)
                        token = await self._extract_token(page)
                        if token:
                            print(f"✅ hCaptcha auto-solved after {i+16} seconds total!")
                            return {"token": token}
            except:
                pass

            # Final token check
            token = await self._extract_token(page)
            if token:
                return {"token": token}

            raise RuntimeError("hCaptcha: No token received and challenge not auto-solved")

        finally:
            await page.close()'''

if old_solve in content:
    content = content.replace(old_solve, new_solve)
    with open('/home/deploy/github/anticaptcha/workers/solvers/hcaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Updated hCaptcha solver to wait longer for auto-solve")
else:
    print("❌ Could not find the exact section to replace")