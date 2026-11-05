#!/usr/bin/env python3
"""Multiple attempts to solve reCAPTCHA"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from ultralytics import YOLO


yolo_model = YOLO('yolov8n-cls.pt')


async def solve_attempt(attempt_num):
    """Single solving attempt"""
    print(f"\n{'='*60}")
    print(f"ATTEMPT #{attempt_num}")
    print(f"{'='*60}\n")
    
    page = await browser_manager.new_page()
    
    try:
        # Load page
        print("1️⃣ Loading page...")
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Loaded\n")
        
        # Wait extra time for reCAPTCHA to fully initialize
        await asyncio.sleep(3)
        
        # Click checkbox
        print("2️⃣ Clicking checkbox...")
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Clicked\n")
        
        # Wait longer for challenge
        print("3️⃣ Waiting 5 seconds for challenge...")
        await asyncio.sleep(5)
        
        # Check for challenge
        challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
        
        try:
            await challenge_frame.wait_for_selector('.rc-imageselect', timeout=3000)
            print("   ✅ Challenge appeared!\n")
            
            # Get instruction
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"   📋 Instruction: {instruction}\n")
            
            # Simple check - does instruction contain any keyword?
            instruction_lower = instruction.lower()
            target = None
            for keyword in ['bus', 'car', 'truck', 'bicycle', 'traffic light', 'crosswalk']:
                if keyword in instruction_lower:
                    target = keyword
                    break
            
            if target:
                print(f"   🎯 Target: {target}\n")
                
                # For demo, just click random tiles to show it works
                print("4️⃣ Clicking tiles (demo)...")
                tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
                
                # Click first 2-3 tiles as demo
                for i in range(min(3, len(tiles))):
                    await tiles[i].click()
                    await asyncio.sleep(0.5)
                    print(f"   Clicked tile {i+1}")
                
                print(f"\n   ✅ Selected tiles\n")
                
                # Click verify
                print("5️⃣ Clicking verify...")
                verify_button = challenge_frame.locator('#recaptcha-verify-button')
                await verify_button.click()
                print("   ✅ Clicked\n")
                
                # Wait for result
                print("6️⃣ Waiting for result...")
                await asyncio.sleep(5)
                
                # Check token
                token = await page.evaluate('''
                    () => document.getElementById('g-recaptcha-response')?.value
                ''')
                
                if token and len(token) > 10:
                    print(f"\n   ✅✅✅ TOKEN RECEIVED: {token[:50]}...\n")
                    return {"success": True, "token": token}
                else:
                    print(f"\n   ⚠️ No token yet\n")
                    return {"success": False, "reason": "no_token"}
            else:
                print(f"   ⚠️ Could not extract target from instruction\n")
                return {"success": False, "reason": "unknown_target"}
        
        except:
            # No challenge
            print("   ℹ️ No challenge appeared\n")
            
            # Check for token directly
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            
            if token and len(token) > 10:
                print(f"   ✅ Token already present: {token[:50]}...\n")
                return {"success": True, "token": token, "auto": True}
            else:
                print(f"   ⚠️ No token\n")
                return {"success": False, "reason": "no_challenge_no_token"}
    
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return {"success": False, "error": str(e)}
    
    finally:
        await page.close()


async def main():
    """Run multiple attempts"""
    print("\n🚀 reCAPTCHA Multiple Attempts Test")
    print("="*60)
    
    results = []
    
    # Try 3 times
    for i in range(1, 4):
        try:
            result = await solve_attempt(i)
            results.append(result)
            
            if result.get('success'):
                print(f"\n✅ SUCCESS on attempt #{i}!")
                break
            
            # Wait before next attempt
            if i < 3:
                print("\n⏳ Waiting 5 seconds before next attempt...\n")
                await asyncio.sleep(5)
        
        except Exception as e:
            print(f"\n❌ Attempt {i} failed: {e}\n")
            results.append({"success": False, "error": str(e)})
    
    # Cleanup
    await browser_manager.close()
    
    # Summary
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)
    
    successful = [r for r in results if r.get('success')]
    
    if successful:
        print(f"\n✅ Solved on attempt #{results.index(successful[0])+1}")
        if successful[0].get('auto'):
            print("   (Auto-solved without challenge)")
        print(f"   Token: {successful[0]['token'][:80]}...")
    else:
        print(f"\n⚠️ Could not solve after {len(results)} attempts")
        for i, r in enumerate(results, 1):
            print(f"   Attempt {i}: {r.get('reason', r.get('error', 'unknown'))}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())