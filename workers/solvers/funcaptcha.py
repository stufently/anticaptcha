"""FunCaptcha (Arkose Labs) solver"""

import asyncio
import base64
import json
import random
import tempfile
from typing import Dict, Any, Optional

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        FUN_CAPTCHA = "funcaptcha"


class FunCaptchaSolver(BaseSolver):
    """
    Solver for FunCaptcha (Arkose Labs)
    
    FunCaptcha shows interactive challenges:
    - Rotate images to correct orientation
    - Drag objects to correct position
    - Select matching images
    - Audio challenges
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.FUN_CAPTCHA
        
    async def detect(self, page) -> bool:
        """Check if FunCaptcha is present"""
        selectors = [
            'iframe[src*="funcaptcha"]',
            '#funcaptcha',
            '.arkose-iframe',
            'div[class*="arkose"]',
        ]
        
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve FunCaptcha
        
        Args:
            page: Playwright page
            challenge_element: FunCaptcha iframe or container
            **kwargs: Must include 'public_key', 'page_url'
        """
        try:
            print("🔍 Solving FunCaptcha...")
            
            # Get parameters
            public_key = kwargs.get('public_key')
            page_url = kwargs.get('page_url', page.url)
            
            if not public_key:
                # Try to extract from page
                public_key = await self._extract_public_key(page)
                
            if not public_key:
                print("❌ Public key not found")
                return False
                
            print(f"   Public key: {public_key[:30]}...")
            
            # Detect challenge type
            challenge_type = await self._detect_challenge_type(page)
            print(f"   Challenge type: {challenge_type}")
            
            if challenge_type == "rotate":
                return await self._solve_rotate(page)
            elif challenge_type == "drag":
                return await self._solve_drag(page)
            elif challenge_type == "select":
                return await self._solve_select(page)
            else:
                print("⚠️ Unknown challenge type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving FunCaptcha: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _extract_public_key(self, page) -> Optional[str]:
        """Extract public key from page"""
        # Check data attributes
        for attr in ['data-pkey', 'data-public-key', 'data-sitekey']:
            key = await page.get_attribute(f'[{attr}]', attr)
            if key:
                return key
                
        # Check script content
        scripts = await page.locator('script').all()
        for script in scripts:
            content = await script.text_content()
            if 'public_key' in content or 'pkey' in content:
                import re
                match = re.search(r'["\']public_key["\']\s*:\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
                    
        return None
        
    async def _detect_challenge_type(self, page) -> str:
        """Detect which type of FunCaptcha challenge is shown"""
        
        # Rotate: icon/image to drag
        if await page.locator('.rotate-icon, [class*="rotate"]').count() > 0:
            return "rotate"
            
        # Drag: draggable elements
        if await page.locator('[class*="drag"], [draggable="true"]').count() > 0:
            return "drag"
            
        # Select: multiple images
        if await page.locator('.fc-images, .arkose-images img').count() > 0:
            return "select"
            
        return "unknown"
        
    async def _solve_rotate(self, page) -> bool:
        """Solve rotation challenge"""
        try:
            print("   Solving rotation challenge...")
            
            # Find rotation element
            rotate_elem = page.locator('.rotate-icon, [class*="rotate"]')
            
            if await rotate_elem.count() == 0:
                print("   ❌ Rotation element not found")
                return False
                
            # Get image
            screenshot = await rotate_elem.screenshot()
            
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Ask Vision LLM for rotation angle
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this image from FunCaptcha rotation challenge. What is the correct rotation angle (0-360 degrees) to make it upright? Return ONLY a JSON number, no explanation: {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Parse angle
                    try:
                        angle = float(result.stdout.strip())
                        print(f"   Detected angle: {angle}°")
                    except:
                        print("   ⚠️ Could not parse angle, trying common values")
                        # Try common angles
                        for test_angle in [90, 180, 270]:
                            success = await self._perform_rotation(page, rotate_elem, test_angle)
                            if success:
                                return True
                        return False
                        
                    # Perform rotation
                    return await self._perform_rotation(page, rotate_elem, angle)
                    
                finally:
                    import os
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _perform_rotation(self, page, element, angle: float) -> bool:
        """Perform rotation drag gesture"""
        try:
            # Get element center
            box = await element.bounding_box()
            if not box:
                return False
                
            center_x = box['x'] + box['width'] / 2
            center_y = box['y'] + box['height'] / 2
            
            # Calculate drag points for rotation
            radius = min(box['width'], box['height']) / 2
            
            # Start point (right side)
            start_x = center_x + radius
            start_y = center_y
            
            # End point based on angle
            import math
            end_x = center_x + radius * math.cos(math.radians(angle))
            end_y = center_y + radius * math.sin(math.radians(angle))
            
            # Perform drag
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            
            # Move in arc
            steps = 10
            for i in range(steps):
                t = i / steps
                curr_x = start_x + (end_x - start_x) * t
                curr_y = start_y + (end_y - start_y) * t
                await page.mouse.move(curr_x, curr_y)
                await asyncio.sleep(0.05)
                
            await page.mouse.up()
            
            # Click verify
            await asyncio.sleep(1)
            verify_button = page.locator('.verify-button, [class*="verify"]')
            if await verify_button.count() > 0:
                await self.click_with_delay(verify_button)
                
            print("✅ Rotation performed")
            return True
            
        except Exception as e:
            print(f"   Error performing rotation: {e}")
            return False
            
    async def _solve_drag(self, page) -> bool:
        """Solve drag challenge"""
        try:
            print("   Solving drag challenge...")
            
            # Find draggable and target
            draggable = page.locator('[class*="drag"], [draggable="true"]')
            target = page.locator('.drop-target, [class*="target"]')
            
            if await draggable.count() == 0 or await target.count() == 0:
                print("   ❌ Elements not found")
                return False
                
            # Get positions
            drag_box = await draggable.first.bounding_box()
            target_box = await target.bounding_box()
            
            if not drag_box or not target_box:
                return False
                
            # Perform drag
            drag_center_x = drag_box['x'] + drag_box['width'] / 2
            drag_center_y = drag_box['y'] + drag_box['height'] / 2
            target_center_x = target_box['x'] + target_box['width'] / 2
            target_center_y = target_box['y'] + target_box['height'] / 2
            
            await page.mouse.move(drag_center_x, drag_center_y)
            await page.mouse.down()
            await asyncio.sleep(0.2)
            await page.mouse.move(target_center_x, target_center_y, steps=10)
            await asyncio.sleep(0.2)
            await page.mouse.up()
            
            # Click verify
            await asyncio.sleep(1)
            verify_button = page.locator('.verify-button, [class*="verify"]')
            if await verify_button.count() > 0:
                await self.click_with_delay(verify_button)
                
            print("✅ Drag performed")
            return True
            
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_select(self, page) -> bool:
        """Solve image selection challenge"""
        try:
            print("   Solving selection challenge...")
            
            # Get instruction
            instruction_elem = page.locator('.fc-instructions, .arkose-instructions')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else ""
            
            # Get images
            images = await page.locator('.fc-images img, .arkose-images img').all()
            
            if not images:
                print("   ❌ No images found")
                return False
                
            print(f"   Found {len(images)} images")
            
            # Take screenshot
            container = page.locator('.fc-images, .arkose-images')
            screenshot = await container.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Determine grid
                grid_size = f"{len(images) // 3}x3" if len(images) % 3 == 0 else f"{len(images)}"
                
                # Classify
                indices = await classifier.classify_tiles(
                    screenshot,
                    instruction,
                    grid_size
                )
                
                print(f"   Vision LLM selected: {indices}")
                
                # Click images
                for idx in indices:
                    if 0 <= idx < len(images):
                        await self.click_with_delay(images[idx])
                        await asyncio.sleep(0.3)
                        
                # Submit
                verify_button = page.locator('.verify-button, [class*="verify"]')
                if await verify_button.count() > 0:
                    await self.click_with_delay(verify_button)
                    
                print("✅ Selection performed")
                return True
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False