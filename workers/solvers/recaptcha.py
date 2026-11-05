"""reCAPTCHA v2/v3 solvers with stealth capabilities"""
import asyncio
import random
from typing import Dict, Any, List
from app.utils.captcha_solver import BaseSolver
from app.utils.browser import browser_manager
from app.config import settings
import json

try:
    from ultralytics import YOLO
    import numpy as np
    from PIL import Image
    import io
    HAS_ML = True
except ImportError:
    HAS_ML = False
    YOLO = None


class RecaptchaV2Solver(BaseSolver):
    """Solve reCAPTCHA v2 with stealth and Yolo classification"""
    
    def __init__(self):
        super().__init__()
        self.yolo_model = None
    
    async def setup(self):
        """Setup solver and load Yolo model"""
        if HAS_ML:
            try:
                # Use detection model instead of classification
                self.yolo_model = YOLO('yolov8n.pt')  # Detection model
                print("✅ Yolo detection model loaded for reCAPTCHA")
            except Exception as e:
                print(f"⚠️ Could not load Yolo: {e}")
    
    async def cleanup(self):
        """Cleanup resources"""
        pass
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v2 with stealth
        
        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com"
            }
        
        Returns:
            {"token": "..."}
        """
        site_key = input_data.get("site_key")
        page_url = input_data.get("page_url")
        
        if not site_key or not page_url:
            raise ValueError("Missing site_key or page_url")
        
        # Create stealth page
        page = await browser_manager.new_page(stealth=True)
        
        try:
            # Navigate
            print(f"🌐 Navigating to {page_url}")
            await page.goto(page_url, timeout=settings.browser_timeout * 1000, wait_until='domcontentloaded')
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # Find reCAPTCHA iframe
            print("🔍 Finding reCAPTCHA widget...")
            await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=15000)
            
            # Click checkbox
            print("✅ Clicking checkbox...")
            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
            await checkbox_frame.locator('#recaptcha-anchor').click()
            await asyncio.sleep(random.uniform(3.0, 5.0))
            
            # Check for token
            token = await self._extract_token(page)
            
            if token:
                print(f"✅ Token received!")
                return {"token": token}
            
            # Check for image challenge
            print("⚠️ Image challenge detected, solving...")
            challenge_frame = page.frame_locator('iframe[src*="bframe"]')
            
            # Get challenge instruction
            instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
            print(f"📋 Challenge: {instruction[:60]}")
            
            # Extract target keyword
            target = self._extract_target(instruction)
            if not target:
                raise ValueError(f"Unknown challenge: {instruction}")
            
            print(f"🎯 Target: {target}")
            
            # Solve image challenge with Yolo
            if self.yolo_model:
                result = await self._solve_image_challenge(page, challenge_frame, target)
                
                if result:
                    # Check for token
                    await asyncio.sleep(3)
                    token = await self._extract_token(page)
                    
                    if token:
                        print(f"✅ Challenge solved! Token: {token[:50]}...")
                        return {"token": token}
            
            raise RuntimeError("Could not solve image challenge")
        
        finally:
            await page.close()
    
    def _extract_target(self, instruction: str) -> str:
        """Extract target keyword from instruction"""
        instruction_lower = instruction.lower()
        keywords = [
            'bus', 'car', 'truck', 'bicycle', 'motorcycle',
            'traffic light', 'crosswalk', 'fire hydrant',
            'stairs', 'bridge', 'mountain', 'palm tree', 'chimney',
            'traffic_signals', 'pedestrian'
        ]
        
        for keyword in keywords:
            if keyword in instruction_lower:
                return keyword
        
        return None
    
    async def _solve_image_challenge(self, page, challenge_frame, target: str) -> bool:
        """Solve image challenge using Yolo"""
        print(f"🤖 Solving challenge for: {target}")
        
        # Get all image tiles
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        print(f"📸 Found {len(tiles)} images")
        
        # Classify each image
        selected = []
        for i, tile in enumerate(tiles):
            img = tile.locator('img')
            
            # Take screenshot
            screenshot = await img.screenshot()
            
            # Classify with Yolo
            if HAS_ML and self.yolo_model:
                should_select = await self._classify_image(screenshot, target)
                
                if should_select:
                    print(f"   Image {i+1}: ✅ SELECT")
                    await tile.click()
                    selected.append(i)
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                else:
                    print(f"   Image {i+1}: ❌ Skip")
        
        print(f"✅ Selected {len(selected)} images")
        
        if selected:
            # Click verify
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True
        
        return False
    
    async def _classify_image(self, image_bytes: bytes, target: str) -> bool:
        """Classify image with Yolo (object detection)"""
        try:
            # Open image
            img = Image.open(io.BytesIO(image_bytes))
            
            # Detect objects
            results = self.yolo_model(img, verbose=False)
            
            # Get detected objects
            if results and len(results) > 0:
                boxes = results[0].boxes
                
                # Check if target object is detected
                for box in boxes:
                    class_id = int(box.cls[0])
                    class_name = results[0].names[class_id].lower()
                    confidence = float(box.conf[0])
                    
                    # Map target to COCO classes
                    target_mapping = {
                        'car': ['car', 'truck', 'bus', 'motorcycle'],
                        'bus': ['bus'],
                        'truck': ['truck'],
                        'bicycle': ['bicycle'],
                        'motorcycle': ['motorcycle'],
                        'traffic light': ['traffic light'],
                        'fire hydrant': ['fire hydrant'],
                    }
                    
                    allowed_classes = target_mapping.get(target, [target])
                    
                    if any(tc in class_name for tc in allowed_classes) and confidence > 0.3:
                        return True
            
            return False
        
        except Exception as e:
            print(f"   ⚠️ Classification error: {e}")
            return False
    
    async def _extract_token(self, page) -> str:
        """Extract reCAPTCHA token"""
        try:
            token = await page.evaluate('''
                () => document.getElementById('g-recaptcha-response')?.value
            ''')
            return token if token and len(token) > 10 else None
        except:
            return None


class RecaptchaV3Solver(BaseSolver):
    """Solve reCAPTCHA v3 (invisible)"""
    
    def __init__(self):
        super().__init__()
    
    async def setup(self):
        """Setup solver"""
        pass
    
    async def cleanup(self):
        """Cleanup resources"""
        pass
    
    async def solve(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v3
        
        Args:
            input_data: {
                "site_key": "6Le...",
                "page_url": "https://example.com",
                "action": "submit"  # optional
            }
        
        Returns:
            {"token": "..."}
        """
        site_key = input_data.get("site_key")
        page_url = input_data.get("page_url")
        action = input_data.get("action", "submit")
        
        if not site_key or not page_url:
            raise ValueError("Missing site_key or page_url")
        
        page = await browser_manager.new_page()
        
        try:
            # Navigate to page
            await page.goto(page_url, timeout=settings.browser_timeout * 1000)
            
            # Execute reCAPTCHA v3
            token = await page.evaluate('''
                async (args) => {
                    return new Promise((resolve) => {
                        grecaptcha.ready(async () => {
                            const token = await grecaptcha.execute(args.site_key, {
                                action: args.action
                            });
                            resolve(token);
                        });
                    });
                }
            ''', {"site_key": site_key, "action": action})
            
            return {"token": token}
        
        finally:
            await page.close()