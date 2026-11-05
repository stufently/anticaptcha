#!/usr/bin/env python3
"""Detailed reCAPTCHA v2 solving test"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager


async def solve_recaptcha_detailed():
    """Detailed reCAPTCHA solving with step-by-step logging"""
    print("🔍 Starting detailed reCAPTCHA v2 test...\n")
    
    page = await browser_manager.new_page()
    
    try:
        # 1. Navigate to page
        print("1️⃣ Navigating to Google reCAPTCHA demo...")
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Page loaded\n")
        
        # 2. Get site info
        print("2️⃣ Extracting page info...")
        site_key = await page.evaluate('''
            () => {
                const iframe = document.querySelector('iframe[src*="recaptcha"]');
                if (!iframe) return null;
                const src = iframe.getAttribute('src');
                const match = src.match(/[?&]k=([^&]+)/);
                return match ? match[1] : null;
            }
        ''')
        print(f"   🔑 Site key: {site_key}\n")
        
        # 3. Wait for reCAPTCHA iframe
        print("3️⃣ Waiting for reCAPTCHA widget...")
        await page.wait_for_selector('iframe[src*="recaptcha"][title*="reCAPTCHA"]', timeout=15000)
        print("   ✅ reCAPTCHA iframe found\n")
        
        # 4. Click checkbox
        print("4️⃣ Clicking reCAPTCHA checkbox...")
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Checkbox clicked\n")
        
        # 5. Wait and check for challenge or token
        print("5️⃣ Waiting for response...")
        
        for attempt in range(10):
            await asyncio.sleep(1)
            print(f"   ⏳ Attempt {attempt + 1}/10...")
            
            # Check for token
            token = await page.evaluate('''
                () => {
                    const textarea = document.getElementById('g-recaptcha-response');
                    return textarea?.value || null;
                }
            ''')
            
            if token and len(token) > 10:
                print(f"\n   ✅✅✅ SUCCESS! Token received!")
                print(f"   📝 Token: {token[:100]}...")
                print(f"   📏 Length: {len(token)} characters\n")
                
                # Verify token by submitting form
                print("6️⃣ Submitting form with token...")
                submit_button = await page.query_selector('input[type="submit"]')
                if submit_button:
                    await submit_button.click()
                    await asyncio.sleep(2)
                    
                    # Check result
                    result_text = await page.evaluate('''
                        () => {
                            const success = document.querySelector('.recaptcha-success');
                            return success?.textContent || null;
                        }
                    ''')
                    
                    if result_text:
                        print(f"   ✅ Verification successful: {result_text}\n")
                    else:
                        print("   ⚠️ Form submitted, checking result...\n")
                
                return {
                    "success": True,
                    "token": token,
                    "token_length": len(token),
                    "site_key": site_key
                }
            
            # Check for challenge
            try:
                challenge_visible = await page.evaluate('''
                    () => {
                        const challenge = document.querySelector('iframe[src*="bframe"]');
                        return challenge !== null;
                    }
                ''')
                
                if challenge_visible:
                    print(f"\n   ⚠️ Image challenge appeared!")
                    
                    # Try to get challenge info
                    challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
                    
                    # Get challenge instruction
                    instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
                    print(f"   📋 Instruction: {instruction}\n")
                    
                    # Get challenge images
                    images = await challenge_frame.locator('.rc-image-tile-wrapper img').count()
                    print(f"   🖼️ Challenge has {images} images")
                    print("   ⚠️ Requires ML model (Yolo) to solve image challenge")
                    
                    return {
                        "success": False,
                        "reason": "image_challenge",
                        "instruction": instruction,
                        "images_count": images,
                        "site_key": site_key,
                        "note": "Requires Yolo model for image classification"
                    }
            
            except Exception as e:
                # No challenge frame visible
                pass
        
        print("\n   ⚠️ No token received after 10 seconds\n")
        
        return {
            "success": False,
            "reason": "timeout",
            "site_key": site_key
        }
    
    except Exception as e:
        print(f"\n   ❌ Error: {e}\n")
        return {
            "success": False,
            "error": str(e)
        }
    
    finally:
        print("7️⃣ Cleaning up...")
        await page.close()
        await browser_manager.close()
        print("   ✅ Done\n")


async def main():
    result = await solve_recaptcha_detailed()
    
    print("="*60)
    print("📊 FINAL RESULT")
    print("="*60)
    
    if result.get('success'):
        print("\n✅ reCAPTCHA SOLVED SUCCESSFULLY!")
        print(f"   Token: {result['token'][:80]}...")
    else:
        print(f"\n⚠️ Could not solve: {result.get('reason', result.get('error', 'unknown'))}")
        
        if result.get('reason') == 'image_challenge':
            print(f"\n   📋 Challenge: {result.get('instruction')}")
            print(f"   🖼️ Images: {result.get('images_count')}")
            print("\n   💡 To solve image challenges, you need to:")
            print("      1. Install ML models: pip install ultralytics easyocr")
            print("      2. Download Yolo model for image classification")
            print("      3. Train or use pre-trained model for CAPTCHA images")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())