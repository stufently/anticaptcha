#!/usr/bin/env python3
"""Solve reCAPTCHA v2 image challenge with Yolo"""
import asyncio
import sys
import base64
import io
sys.path.insert(0, '/app')

from app.utils.browser import browser_manager
from ultralytics import YOLO
from PIL import Image


# Load Yolo model
print("🔄 Loading Yolo model...")
yolo_model = YOLO('yolov8n-cls.pt')
print("✅ Yolo model loaded\n")


# Mapping reCAPTCHA instructions to Yolo classes
RECAPTCHA_TO_YOLO = {
    'bus': ['bus', 'minibus'],
    'car': ['car', 'suv', 'pickup', 'van'],
    'truck': ['truck', 'pickup_truck'],
    'bicycle': ['bicycle', 'bike'],
    'motorcycle': ['motorcycle', 'motorbike'],
    'traffic light': ['traffic_light', 'traffic_signals'],
    'crosswalk': ['crosswalk', 'pedestrian_crossing'],
    'fire hydrant': ['fire_hydrant'],
    'stairs': ['stairs', 'staircase'],
    'bridge': ['bridge'],
    'mountain': ['mountain', 'mountains'],
    'palm tree': ['palm_tree'],
    'chimney': ['chimney'],
}


def extract_keyword(instruction):
    """Extract keyword from reCAPTCHA instruction"""
    instruction_lower = instruction.lower()
    
    # Common patterns
    keywords = [
        'bus', 'car', 'truck', 'bicycle', 'motorcycle',
        'traffic light', 'crosswalk', 'fire hydrant',
        'stairs', 'bridge', 'mountain', 'palm tree', 'chimney'
    ]
    
    for keyword in keywords:
        if keyword in instruction_lower:
            return keyword
    
    return None


async def classify_image(image_element, target_keyword):
    """Classify image and check if it contains target object"""
    try:
        # Take screenshot of image
        screenshot_bytes = await image_element.screenshot()
        
        # Convert to PIL Image
        image = Image.open(io.BytesIO(screenshot_bytes))
        
        # Classify with Yolo
        results = yolo_model(image)
        
        # Get top predictions
        predictions = results[0].probs
        
        # Get all class names
        class_names = results[0].names
        
        # Check if target is in top predictions
        target_classes = RECAPTCHA_TO_YOLO.get(target_keyword, [target_keyword])
        
        for i, prob in enumerate(predictions.data.tolist()[:10]):  # Top 10
            class_name = class_names[i].lower().replace(' ', '_')
            if any(tc in class_name for tc in target_classes) and prob > 0.3:
                return True, class_name, prob
        
        return False, None, 0.0
    
    except Exception as e:
        print(f"   ⚠️ Error classifying image: {e}")
        return False, None, 0.0


async def solve_recaptcha_with_yolo():
    """Solve reCAPTCHA with Yolo classification"""
    print("🚀 Starting reCAPTCHA solving with Yolo classification...\n")
    
    page = await browser_manager.new_page()
    
    try:
        # Navigate
        print("1️⃣ Loading reCAPTCHA demo...")
        await page.goto(
            'https://www.google.com/recaptcha/api2/demo',
            timeout=60000,
            wait_until='networkidle'
        )
        print("   ✅ Page loaded\n")
        
        # Click checkbox
        print("2️⃣ Clicking reCAPTCHA checkbox...")
        checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
        await checkbox_frame.locator('#recaptcha-anchor').click()
        print("   ✅ Checkbox clicked\n")
        
        # Wait for challenge
        print("3️⃣ Waiting for challenge...")
        await asyncio.sleep(2)
        
        # Check for challenge
        try:
            challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
            await challenge_frame.wait_for_selector('.rc-imageselect', timeout=5000)
            print("   ✅ Image challenge detected\n")
            
            # Get instruction
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"4️⃣ Challenge instruction: {instruction}\n")
            
            # Extract keyword
            target_keyword = extract_keyword(instruction)
            if not target_keyword:
                print(f"   ⚠️ Unknown target in instruction: {instruction}")
                return {"success": False, "reason": "unknown_target"}
            
            print(f"   🎯 Target: {target_keyword}\n")
            
            # Get all images
            print("5️⃣ Analyzing images...")
            images = await challenge_frame.locator('.rc-image-tile-wrapper').all()
            print(f"   📸 Found {len(images)} images\n")
            
            # Classify each image
            selected_count = 0
            for i, image_wrapper in enumerate(images):
                img_element = image_wrapper.locator('img')
                
                should_select, class_name, prob = await classify_image(img_element, target_keyword)
                
                print(f"   Image {i+1}: ", end="")
                if should_select:
                    print(f"✅ SELECT ({class_name}, {prob:.2f})")
                    await image_wrapper.click()
                    selected_count += 1
                    await asyncio.sleep(0.5)  # Wait for tile to update
                else:
                    print(f"❌ Skip")
            
            print(f"\n   ✅ Selected {selected_count} images\n")
            
            # Click verify
            print("6️⃣ Clicking verify...")
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            print("   ✅ Verify clicked\n")
            
            # Wait for result
            print("7️⃣ Waiting for solution...")
            await asyncio.sleep(5)
            
            # Check for token
            token = await page.evaluate('''
                () => {
                    return document.getElementById('g-recaptcha-response')?.value;
                }
            ''')
            
            if token and len(token) > 10:
                print(f"\n✅✅✅ SUCCESS! reCAPTCHA SOLVED!")
                print(f"   Token: {token[:100]}...")
                print(f"   Length: {len(token)}\n")
                
                return {
                    "success": True,
                    "token": token,
                    "instruction": instruction,
                    "target": target_keyword,
                    "selected_images": selected_count
                }
            else:
                print(f"\n⚠️ No token received after solving")
                
                # Check for new challenge
                try:
                    new_instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
                    if new_instruction != instruction:
                        print(f"   New challenge appeared: {new_instruction}")
                        print("   💡 Would need to solve multiple challenges")
                except:
                    pass
                
                return {
                    "success": False,
                    "reason": "no_token_after_solve"
                }
        
        except Exception as e:
            # No challenge - might be already solved
            print(f"   ℹ️ No challenge detected, checking token...")
            
            await asyncio.sleep(3)
            token = await page.evaluate('''
                () => {
                    return document.getElementById('g-recaptcha-response')?.value;
                }
            ''')
            
            if token and len(token) > 10:
                print(f"\n✅ reCAPTCHA auto-solved!")
                print(f"   Token: {token[:100]}...\n")
                return {"success": True, "token": token}
            else:
                print(f"\n⚠️ No challenge and no token\n")
                return {"success": False, "reason": "no_challenge_no_token"}
    
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        return {"success": False, "error": str(e)}
    
    finally:
        print("8️⃣ Cleanup...")
        await page.close()
        await browser_manager.close()
        print("   ✅ Done\n")


async def main():
    result = await solve_recaptcha_with_yolo()
    
    print("="*60)
    print("📊 FINAL RESULT")
    print("="*60)
    
    if result.get('success'):
        print("\n✅ reCAPTCHA SOLVED SUCCESSFULLY WITH YOLO!")
        print(f"   Target: {result.get('target', 'unknown')}")
        print(f"   Images selected: {result.get('selected_images', 0)}")
        print(f"   Token: {result['token'][:80]}...")
    else:
        print(f"\n⚠️ Could not solve: {result.get('reason', result.get('error'))}")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())