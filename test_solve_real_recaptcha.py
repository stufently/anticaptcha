#!/usr/bin/env python3
"""Final test: solve real reCAPTCHA with stealth and Yolo"""
import asyncio
import sys
sys.path.insert(0, '/app')

from workers.solvers.recaptcha import RecaptchaV2Solver


async def main():
    """Test real reCAPTCHA solving"""
    print("🚀 Testing Real reCAPTCHA v2 Solving")
    print("="*60)
    print("   Site: Google reCAPTCHA Demo")
    print("   URL: https://www.google.com/recaptcha/api2/demo")
    print("="*60 + "\n")
    
    # Create solver
    solver = RecaptchaV2Solver()
    
    # Setup (load Yolo)
    print("1️⃣ Setting up solver...")
    await solver.setup()
    print()
    
    try:
        # Solve
        print("2️⃣ Solving reCAPTCHA...")
        result = await solver.solve({
            "site_key": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
            "page_url": "https://www.google.com/recaptcha/api2/demo"
        })
        
        print("\n" + "="*60)
        if result.get('token'):
            print("✅✅✅ SUCCESS!")
            print("="*60)
            print(f"\nToken: {result['token'][:100]}...")
            print(f"Length: {len(result['token'])} characters\n")
            return True
        else:
            print("⚠️ No token received")
            print("="*60)
            return False
    
    except Exception as e:
        print("\n" + "="*60)
        print(f"❌ Error: {e}")
        print("="*60)
        return False
    
    finally:
        await solver.cleanup()


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)