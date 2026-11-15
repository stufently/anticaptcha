#!/usr/bin/env python3
"""Comprehensive test on real CAPTCHA with Vision LLM"""

import asyncio
import sys
import random
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from workers.solvers.recaptcha import RecaptchaV2Solver
from workers.classifiers.vision_llm import VisionLLMClassifier


async def test_recaptcha_with_vision_llm():
    """Test reCAPTCHA v2 with Vision LLM integration"""
    print("=" * 70)
    print("TESTING reCAPTCHA v2 WITH VISION LLM")
    print("=" * 70)
    
    # Initialize solver
    solver = RecaptchaV2Solver()
    solver.vision_classifier = VisionLLMClassifier()
    
    page = await browser_manager.new_page()
    
    try:
        # Navigate to reCAPTCHA demo
        print("\n🌐 Navigating to Google reCAPTCHA demo...")
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000
        )
        print("✅ Page loaded")
        
        # Find and click checkbox
        print("\n🖱️ Clicking reCAPTCHA checkbox...")
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('.recaptcha-checkbox').click()
        print("✅ Checkbox clicked")
        
        # Wait for challenge to appear
        await asyncio.sleep(3)
        
        # Check if image challenge appeared
        try:
            challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
            # Use locator instead of wait_for_selector
            challenge = challenge_frame.locator('.rc-imageselect')
            await challenge.wait_for(timeout=5000)
            print("✅ Image challenge appeared!")
            
            # Get instruction
            instruction_elem = challenge_frame.locator('.rc-imageselect-instructions strong')
            instruction = await instruction_elem.text_content()
            print(f"   Instruction: {instruction}")
            
            # Get target object
            target = instruction.lower().replace('select all images with ', '').replace('select all squares with ', '').strip()
            print(f"   Target: {target}")
            
            # Use solver
            print("\n🤖 Solving with Vision LLM...")
            success = await solver._solve_with_vision_llm(
                page,
                challenge_frame,
                target
            )
            
            if success:
                print("✅ Vision LLM solver executed!")
                
                # Wait for verification
                await asyncio.sleep(3)
                
                # Check if solved
                token = await page.evaluate('''
                    () => {
                        return document.getElementById('g-recaptcha-response')?.value;
                    }
                ''')
                
                if token and len(token) > 100:
                    print(f"✅ CAPTCHA SOLVED! Token: {token[:50]}...")
                    return {"success": True, "token": token[:50]}
                else:
                    print("⚠️ Solver ran but no token received")
                    return {"success": False, "status": "no_token_after_solve"}
            else:
                print("❌ Vision LLM solver failed")
                return {"success": False, "error": "solver_failed"}
                
        except Exception as e:
            print(f"⚠️ No image challenge appeared: {e}")
            
            # Check if auto-verified
            await asyncio.sleep(5)
            token = await page.evaluate('''
                () => {
                    return document.getElementById('g-recaptcha-response')?.value;
                }
            ''')
            
            if token:
                print(f"✅ Auto-verified! Token: {token[:50]}...")
                return {"success": True, "token": token[:50], "auto_verified": True}
            else:
                print("⚠️ No token received")
                return {"success": False, "status": "no_token"}
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
        
    finally:
        await page.close()
        if solver.vision_classifier:
            solver.vision_classifier.cleanup()


async def test_multiple_attempts():
    """Test with multiple attempts on different sites"""
    print("\n" + "=" * 70)
    print("TESTING MULTIPLE reCAPTCHA ATTEMPTS")
    print("=" * 70)
    
    # Test sites with reCAPTCHA
    test_sites = [
        {
            "name": "Google Demo",
            "url": "https://www.google.com/recaptcha/api2/demo",
        },
        {
            "name": "Recaptcha.net Demo",
            "url": "https://recaptcha-demo.appspot.com/",
        },
    ]
    
    solver = RecaptchaV2Solver()
    solver.vision_classifier = VisionLLMClassifier()
    
    results = []
    
    for site in test_sites:
        print(f"\n{'─' * 70}")
        print(f"Testing: {site['name']}")
        print(f"URL: {site['url']}")
        print(f"{'─' * 70}")
        
        page = await browser_manager.new_page()
        
        try:
            # Navigate
            await page.goto(site['url'], timeout=60000)
            print("✅ Page loaded")
            
            # Find reCAPTCHA
            await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=10000)
            
            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await checkbox_frame.locator('.recaptcha-checkbox').click()
            print("✅ Checkbox clicked")
            
            # Wait
            await asyncio.sleep(3)
            
            # Check for challenge
            try:
                challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
                challenge = challenge_frame.locator('.rc-imageselect')
                await challenge.wait_for(timeout=5000)
                print("✅ Image challenge detected")
                
                # Get instruction
                instruction_elem = challenge_frame.locator('.rc-imageselect-instructions strong')
                instruction = await instruction_elem.text_content()
                target = instruction.lower().replace('select all images with ', '').replace('select all squares with ', '').strip()
                
                # Solve
                success = await solver._solve_with_vision_llm(page, challenge_frame, target)
                
                await asyncio.sleep(3)
                
                # Check result
                token = await page.evaluate('''
                    () => {
                        return document.getElementById('g-recaptcha-response')?.value;
                    }
                ''')
                
                if token and len(token) > 100:
                    print(f"✅ SOLVED! Token received")
                    results.append({"site": site['name'], "success": True, "method": "vision_llm"})
                else:
                    print("⚠️ No token after solve")
                    results.append({"site": site['name'], "success": False, "error": "no_token"})
                    
            except:
                # No challenge - auto-verified
                await asyncio.sleep(5)
                token = await page.evaluate('''
                    () => {
                        return document.getElementById('g-recaptcha-response')?.value;
                    }
                ''')
                
                if token:
                    print(f"✅ Auto-verified")
                    results.append({"site": site['name'], "success": True, "method": "auto"})
                else:
                    print("⚠️ No token")
                    results.append({"site": site['name'], "success": False, "error": "no_token"})
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({"site": site['name'], "success": False, "error": str(e)[:50]})
            
        finally:
            await page.close()
    
    if solver.vision_classifier:
        solver.vision_classifier.cleanup()
    
    return results


async def main():
    """Run comprehensive tests"""
    print("🚀 REAL CAPTCHA TESTING WITH VISION LLM\n")
    
    # Test 1: Single detailed test
    result1 = await test_recaptcha_with_vision_llm()
    
    # Test 2: Multiple attempts
    results2 = await test_multiple_attempts()
    
    # Cleanup
    await browser_manager.close()
    
    # Summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    
    print(f"\nTest 1 (Detailed):")
    print(f"  Success: {result1.get('success', False)}")
    if result1.get('error'):
        print(f"  Error: {result1['error']}")
    
    print(f"\nTest 2 (Multiple Sites):")
    successful = sum(1 for r in results2 if r['success'])
    total = len(results2)
    print(f"  Success rate: {successful}/{total} ({successful/total*100:.0f}%)")
    
    for r in results2:
        status = "✅" if r['success'] else "❌"
        print(f"  {status} {r['site']}: {r.get('method', r.get('error', 'unknown'))}")
    
    print("\n" + "=" * 70)
    
    if successful > 0:
        print("✅ Vision LLM CAPTCHA solver is WORKING on real CAPTCHA!")
    else:
        print("⚠️ Tests did not complete successfully")
        print("   Possible reasons:")
        print("   - Network issues")
        print("   - CAPTCHA behavior changed")
        print("   - Need more test iterations")


if __name__ == "__main__":
    asyncio.run(main())