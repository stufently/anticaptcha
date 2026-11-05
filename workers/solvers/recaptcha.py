"""reCAPTCHA v2/v3 solvers with stealth capabilities"""
import asyncio
import random
from typing import Dict, Any, List
from app.utils.captcha_solver import BaseSolver
from app.utils.browser import browser_manager
from app.config import settings
import json
import numpy as np

try:
    from ultralytics import YOLO
    from PIL import Image
    import io
    HAS_ML = True
except ImportError:
    HAS_ML = False
    YOLO = None


class RecaptchaV2Solver(BaseSolver):
    """Solve reCAPTCHA v2 with stealth and hybrid classification"""
    
    def __init__(self):
        super().__init__()
        self.yolo_model = None
    
    async def setup(self):
        """Setup solver and load Yolo model"""
        if HAS_ML:
            try:
                # Use detection model
                self.yolo_model = YOLO('yolov8n.pt')
                print("✅ Yolo model loaded for reCAPTCHA")
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
            
            # Solve image challenge with hybrid approach
            if self.yolo_model or HAS_ML:
                result = await self._solve_image_challenge_hybrid(page, challenge_frame, target)
                
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
            'car', 'bus', 'truck', 'bicycle', 'motorcycle',
            'traffic light', 'crosswalk', 'fire hydrant',
            'stairs', 'bridge', 'mountain', 'palm tree', 'chimney',
            'pedestrian', 'taxis'
        ]
        
        for keyword in keywords:
            if keyword in instruction_lower:
                # Normalize
                if keyword == 'traffic light':
                    return 'traffic_light'
                elif keyword == 'fire hydrant':
                    return 'fire_hydrant'
                elif keyword == 'palm tree':
                    return 'palm_tree'
                return keyword
        
        return None
    
    async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:
        """Solve using hybrid Yolo + heuristics approach"""
        print(f"🤖 Solving challenge (hybrid) for: {target}")
        
        # Get all image tiles
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        print(f"📸 Found {len(tiles)} images")
        
        # Classify each image
        selected = []
        for i, tile in enumerate(tiles):
            img = tile.locator('img')
            
            # Take screenshot
            screenshot = await img.screenshot()
            
            # Classify with hybrid approach
            should_select = await self._classify_image_hybrid(screenshot, target)
            
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
    
    async def _classify_image_hybrid(self, image_bytes: bytes, target: str) -> bool:
        """Hybrid classification: Yolo for COCO, heuristics for others"""
        try:
            # Open image
            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)
            
            # COCO classes - use Yolo
            coco_targets = ['car', 'bus', 'truck', 'bicycle', 'motorcycle', 'traffic_light', 'fire_hydrant']
            
            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)
                
                if results and len(results) > 0:
                    boxes = results[0].boxes
                    
                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])
                        
                        # Map
                        if target == 'car' and class_name in ['car', 'truck', 'bus'] and confidence > 0.3:
                            return True
                        elif target == 'bus' and class_name == 'bus' and confidence > 0.3:
                            return True
                        elif target == 'truck' and class_name == 'truck' and confidence > 0.3:
                            return True
                        elif target == 'bicycle' and class_name == 'bicycle' and confidence > 0.3:
                            return True
                        elif target == 'motorcycle' and class_name == 'motorcycle' and confidence > 0.3:
                            return True
                        elif target == 'traffic_light' and class_name == 'traffic light' and confidence > 0.3:
                            return True
                        elif target == 'fire_hydrant' and class_name == 'fire hydrant' and confidence > 0.3:
                            return True
            
            # Heuristics for non-COCO classes
            elif target == 'crosswalk':
                return self._detect_crosswalk(img_array)
            elif target == 'stairs':
                return self._detect_stairs(img_array)
            elif target == 'bridge':
                return self._detect_bridge(img_array)
            elif target == 'mountain':
                return self._detect_mountain(img_array)
            elif target == 'palm_tree':
                return self._detect_palm_tree(img_array)
            
            # Unknown class - conservatively return False
            return False
        
        except Exception as e:
            print(f"      ⚠️ Classification error: {e}")
            return False
    
    def _detect_crosswalk(self, img_array: np.ndarray) -> bool:
        """Detect crosswalk (zebra stripes) - improved"""
        try:
            if len(img_array.shape) == 3:
                # Convert to grayscale
                gray = np.mean(img_array, axis=2)
            else:
                gray = img_array
            
            mean = np.mean(gray)
            
            # Crosswalk has distinctive white stripes on dark background
            # Check for high contrast pattern
            
            # 1. White stripes (significantly brighter than mean)
            white_pixels = gray > mean + 40
            white_ratio = np.sum(white_pixels) / gray.size
            
            # 2. Dark background (significantly darker than mean)
            dark_pixels = gray < mean - 20
            dark_ratio = np.sum(dark_pixels) / gray.size
            
            # 3. Check for striped pattern (alternating)
            # Look for regular horizontal or vertical patterns
            horizontal_variance = np.var(np.sum(white_pixels, axis=1))
            vertical_variance = np.var(np.sum(white_pixels, axis=0))
            
            # Crosswalk should have:
            # - Moderate white ratio (15-40%)
            # - Significant dark background
            # - Regular striped pattern
            
            if 0.15 < white_ratio < 0.40 and dark_ratio > 0.3:
                # Check for pattern regularity
                if horizontal_variance > 1000 or vertical_variance > 1000:
                    return True
            
            return False
        
        except Exception as e:
            print(f"      ⚠️ Crosswalk detection error: {e}")
            return False
    
    def _detect_stairs(self, img_array: np.ndarray) -> bool:
        """Detect stairs (horizontal lines)"""
        try:
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Detect strong horizontal edges
            gradient = np.abs(np.diff(gray, axis=1))
            edge_ratio = np.sum(gradient > 50) / gray.size
            
            return edge_ratio > 0.08
        except:
            return False
    
    def _detect_bridge(self, img_array: np.ndarray) -> bool:
        """Detect bridge (arch/horizontal structure)"""
        # Simple: check for horizontal structure in upper part
        try:
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Upper third
            upper = gray[:gray.shape[0]//3, :]
            
            # Check for continuous structure
            return np.std(upper) > 30
        except:
            return False
    
    def _detect_mountain(self, img_array: np.ndarray) -> bool:
        """Detect mountain (triangular shape, natural colors)"""
        try:
            # Check for triangular/pointed shape in upper region
            gray = np.mean(img_array, axis=2) if len(img_array.shape) == 3 else img_array
            
            # Check variance (mountains have varied terrain)
            return np.std(gray) > 40
        except:
            return False
    
    def _detect_palm_tree(self, img_array: np.ndarray) -> bool:
        """Detect palm tree (green color at top)"""
        try:
            if len(img_array.shape) == 3:
                # Check for green in upper region
                upper = img_array[:img_array.shape[0]//2, :, :]
                
                # Green channel should be dominant
                green_ratio = np.sum(upper[:, :, 1] > upper[:, :, 0] + 20) / upper[:, :, 1].size
                
                return green_ratio > 0.2
            return False
        except:
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