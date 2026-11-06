"""Tencent CAPTCHA solver"""

import asyncio
import json
import random
import re
from typing import Dict, Any, Optional

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        TENCENT = "tencent"


class TencentCaptchaSolver(BaseSolver):
    """
    Solver for Tencent CAPTCHA (TenDI)
    
    Tencent CAPTCHA shows:
    - Slide puzzles
    - Image selection
    - Click verification
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.TENCENT
        
    async def detect(self, page) -> bool:
        """Check if Tencent CAPTCHA is present"""
        selectors = [
            'iframe[src*="captcha.qq.com"]',
            'iframe[src*="tencent"]',
            '#TencentCaptcha',
            '.tcaptcha',
            'div[id*="tencent"]',
        ]
        
        # Check URL
        if 'captcha.qq.com' in page.url or 'tencent' in page.url.lower():
            return True
            
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve Tencent CAPTCHA
        
        Args:
            page: Playwright page
            challenge_element: CAPTCHA container
            **kwargs: Optional parameters
        """
        try:
            print("🔍 Solving Tencent CAPTCHA...")
            
            # Switch to iframe if needed
            if await page.locator('iframe[src*="captcha.qq.com"]').count() > 0:
                iframe = page.frame_locator('iframe[src*="captcha.qq.com"]')
            else:
                iframe = page
                
            # Detect challenge type
            challenge_type = await self._detect_challenge_type(iframe)
            print(f"   Type: {challenge_type}")
            
            if challenge_type == "slide":
                return await self._solve_slide(page, iframe)
            elif challenge_type == "select":
                return await self._solve_select(page, iframe)
            elif challenge_type == "click":
                return await self._solve_click(page, iframe)
            else:
                print("⚠️ Unknown challenge type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving Tencent CAPTCHA: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _detect_challenge_type(self, page_or_frame) -> str:
        """Detect which type of Tencent challenge"""
        
        # Slide puzzle
        if await page_or_frame.locator('.tcaptcha-slider, .slide-block').count() > 0:
            return "slide"
            
        # Image selection
        if await page_or_frame.locator('.tcaptcha-img, .verify-img').count() > 0:
            return "select"
            
        # Click verification
        if await page_or_frame.locator('.click-verify, .btn-verify').count() > 0:
            return "click"
            
        return "unknown"
        
    async def _solve_slide(self, page, iframe) -> bool:
        """Solve slide puzzle"""
        try:
            print("   Solving slide puzzle...")
            
            # Wait for images to load
            await asyncio.sleep(1)
            
            # Get background image
            bg_img = iframe.locator('.tcaptcha-bg, .verify-bg')
            
            if await bg_img.count() == 0:
                print("   ❌ Background image not found")
                return False
                
            # Get screenshot
            bg_screenshot = await bg_img.screenshot()
            
            # Get slider button
            slider = iframe.locator('.tcaptcha-slider-btn, .slide-block')
            
            if await slider.count() == 0:
                print("   ❌ Slider not found")
                return False
                
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(bg_screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this Tencent slide CAPTCHA. Where is the gap? Return X position as percentage (0-100): {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Parse position
                    try:
                        x_percent = float(result.stdout.strip())
                        print(f"   Gap at {x_percent}%")
                    except:
                        print("   ⚠️ Could not parse, trying random")
                        x_percent = random.randint(40, 60)
                        
                    # Get coordinates
                    bg_box = await bg_img.bounding_box()
                    if not bg_box:
                        return False
                        
                    # Get absolute position
                    target_x = bg_box['x'] + (bg_box['width'] * x_percent / 100)
                    
                    # Get slider
                    slider_box = await slider.bounding_box()
                    if not slider_box:
                        return False
                        
                    start_x = slider_box['x'] + slider_box['width'] / 2
                    start_y = slider_box['y'] + slider_box['height'] / 2
                    
                    # Perform drag
                    await page.mouse.move(start_x, start_y)
                    await page.mouse.down()
                    await asyncio.sleep(0.2)
                    
                    distance = target_x - start_x
                    steps = 20
                    for i in range(steps):
                        progress = (i + 1) / steps
                        # Add slight randomness for human-like behavior
                        curr_x = start_x + distance * progress + random.uniform(-2, 2)
                        curr_y = start_y + random.uniform(-2, 2)
                        await page.mouse.move(curr_x, curr_y)
                        await asyncio.sleep(random.uniform(0.02, 0.08))
                        
                    await page.mouse.up()
                    
                    # Wait for verification
                    await asyncio.sleep(3)
                    
                    # Check result
                    success = iframe.locator('.tcaptcha-success, .verify-success')
                    if await success.count() > 0:
                        print("✅ Tencent slide solved!")
                        return True
                    else:
                        print("⚠️ Verification failed")
                        return False
                        
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
            
    async def _solve_select(self, page, iframe) -> bool:
        """Solve image selection"""
        try:
            print("   Solving image selection...")
            
            # Get instruction
            instruction_elem = iframe.locator('.tcaptcha-title, .verify-title')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else ""
            print(f"   Instruction: {instruction}")
            
            # Get images
            images = await iframe.locator('.tcaptcha-img img, .verify-img img').all()
            
            if not images:
                print("   ❌ No images found")
                return False
                
            print(f"   Found {len(images)} images")
            
            # Take screenshot
            container = iframe.locator('.tcaptcha-panel, .verify-panel')
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
                submit = iframe.locator('.tcaptcha-submit, .btn-submit')
                if await submit.count() > 0:
                    await self.click_with_delay(submit)
                    
                await asyncio.sleep(2)
                
                # Check
                success = iframe.locator('.tcaptcha-success, .verify-success')
                if await success.count() > 0:
                    print("✅ Tencent selection solved!")
                    return True
                else:
                    print("⚠️ Verification failed")
                    return False
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_click(self, page, iframe) -> bool:
        """Solve click verification"""
        try:
            print("   Solving click verification...")
            
            # Simply click the verify button
            verify_btn = iframe.locator('.click-verify, .btn-verify, .tcaptcha-btn')
            
            if await verify_btn.count() > 0:
                await self.click_with_delay(verify_btn)
                await asyncio.sleep(2)
                
                # Check
                success = iframe.locator('.tcaptcha-success, .verify-success')
                if await success.count() > 0:
                    print("✅ Click verification solved!")
                    return True
                else:
                    print("⚠️ Verification failed")
                    return False
            else:
                print("   ❌ Verify button not found")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False