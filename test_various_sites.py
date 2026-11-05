#!/usr/bin/env python3
"""Test various CAPTCHA on real websites"""
import asyncio
import sys
import base64
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager


async def test_hcaptcha_discord():
    """Test hCaptcha on Discord"""
    print("\n🔍 Testing hCaptcha on Discord...")
    
    page = await browser_manager.new_page()
    
    try:
        await page.goto('https://discord.com/register', timeout=60000)
        print("   ✅ Page loaded")
        
        # Look for hCaptcha
        await asyncio.sleep(3)
        
        try:
            await page.wait_for_selector('iframe[src*="hcaptcha"]', timeout=10000)
            print("   ✅ hCaptcha found")
            
            # Get site key
            site_key = await page.evaluate('''
                () => {
                    const div = document.querySelector('.h-captcha');
                    return div?.getAttribute('data-sitekey');
                }
            ''')
            print(f"   🔑 Site key: {site_key}")
            
            return {"found": True, "site_key": site_key}
        except:
            print("   ⚠️ hCaptcha not found")
            return {"found": False}
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"error": str(e)}
    
    finally:
        await page.close()


async def test_turnstile_various():
    """Test Turnstile on various sites"""
    print("\n🔍 Testing Turnstile on various sites...")
    
    sites = [
        ('https://www.virustotal.com', 'VirusTotal'),
        ('https://pomf2.lain.la', 'Pomf2'),
    ]
    
    results = []
    page = await browser_manager.new_page()
    
    for url, name in sites:
        print(f"\n   Testing {name} ({url})...")
        try:
            await page.goto(url, timeout=30000, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            
            # Check for Turnstile
            try:
                await page.wait_for_selector('iframe[src*="challenges.cloudflare.com"]', timeout=5000)
                print(f"   ✅ Turnstile found on {name}")
                results.append({"site": name, "found": True})
            except:
                print(f"   ℹ️ No Turnstile on {name}")
                results.append({"site": name, "found": False})
        except Exception as e:
            print(f"   ⚠️ Could not load {name}: {str(e)[:50]}")
            results.append({"site": name, "error": str(e)[:50]})
    
    await page.close()
    return results


async def test_simple_text_captcha():
    """Test simple text CAPTCHA"""
    print("\n🔍 Testing simple text CAPTCHA on demo sites...")
    
    sites = [
        'https://www.captcha.net/index.html',
        'https://codepen.io/alexprut/pen/ZjRBZb',
    ]
    
    results = []
    page = await browser_manager.new_page()
    
    for url in sites:
        print(f"\n   Testing {url}...")
        try:
            await page.goto(url, timeout=30000)
            await asyncio.sleep(2)
            
            # Look for CAPTCHA images
            captcha_imgs = await page.query_selector_all('img[src*="captcha"], img[alt*="captcha"], canvas')
            
            if captcha_imgs:
                print(f"   ✅ Found {len(captcha_imgs)} CAPTCHA elements")
                results.append({"url": url, "found": True, "count": len(captcha_imgs)})
            else:
                print(f"   ℹ️ No CAPTCHA found")
                results.append({"url": url, "found": False})
        
        except Exception as e:
            print(f"   ⚠️ Error: {str(e)[:50]}")
            results.append({"url": url, "error": str(e)[:50]})
    
    await page.close()
    return results


async def test_recaptcha_alternative():
    """Test reCAPTCHA on alternative demo"""
    print("\n🔍 Testing reCAPTCHA on alternative site...")
    
    page = await browser_manager.new_page()
    
    try:
        # Alternative reCAPTCHA demo
        await page.goto('https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php', timeout=60000)
        print("   ✅ Page loaded")
        
        await asyncio.sleep(3)
        
        # Check for reCAPTCHA
        try:
            await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=10000)
            print("   ✅ reCAPTCHA found")
            
            # Click checkbox
            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await checkbox_frame.locator('#recaptcha-anchor').click()
            print("   ✅ Clicked checkbox")
            
            # Wait for challenge or token
            await asyncio.sleep(5)
            
            # Check for challenge
            try:
                challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
                await challenge_frame.wait_for_selector('.rc-imageselect', timeout=3000)
                print("   ✅ Image challenge appeared")
                
                instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
                print(f"   📋 Instruction: {instruction}")
                
                return {"found": True, "challenge": True, "instruction": instruction}
            except:
                # Check for token
                token = await page.evaluate('''
                    () => document.getElementById('g-recaptcha-response')?.value
                ''')
                
                if token:
                    print(f"   ✅ Auto-solved! Token: {token[:50]}...")
                    return {"found": True, "solved": True, "token": token}
                else:
                    print("   ⚠️ No challenge, no token")
                    return {"found": True, "solved": False}
        
        except:
            print("   ⚠️ No reCAPTCHA found")
            return {"found": False}
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"error": str(e)}
    
    finally:
        await page.close()


async def main():
    """Run all tests"""
    print("🚀 Testing CAPTCHA on Real Websites")
    print("="*60)
    
    results = {}
    
    # Test each type
    results['hcaptcha'] = await test_hcaptcha_discord()
    results['turnstile'] = await test_turnstile_various()
    results['simple'] = await test_simple_text_captcha()
    results['recaptcha'] = await test_recaptcha_alternative()
    
    # Cleanup
    await browser_manager.close()
    
    # Summary
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)
    
    print("\n1. hCaptcha (Discord):")
    if results['hcaptcha'].get('found'):
        print("   ✅ Found")
    else:
        print("   ❌ Not found")
    
    print("\n2. Turnstile:")
    for r in results['turnstile']:
        if r.get('found'):
            print(f"   ✅ {r['site']}")
        else:
            print(f"   ❌ {r['site']}")
    
    print("\n3. Simple Text CAPTCHA:")
    for r in results['simple']:
        if r.get('found'):
            print(f"   ✅ {r['url']} ({r['count']} elements)")
        else:
            print(f"   ❌ {r['url']}")
    
    print("\n4. reCAPTCHA (Alternative Demo):")
    if results['recaptcha'].get('challenge'):
        print(f"   ✅ Challenge found: {results['recaptcha']['instruction'][:50]}...")
    elif results['recaptcha'].get('solved'):
        print(f"   ✅ Auto-solved")
    else:
        print(f"   ❌ {results['recaptcha'].get('error', 'Not found')}")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())