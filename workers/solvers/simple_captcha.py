"""Simple CAPTCHA solver using Vision LLM"""

import asyncio
import json
import random
import re
import tempfile
from typing import Dict, Any, Optional

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        SIMPLE_CAPTCHA = "simple_captcha"


class SimpleCaptchaSolver(BaseSolver):
    """
    Solver for simple CAPTCHAs using Vision LLM
    
    Handles:
    - Text on image
    - Simple math
    - Simple puzzles
    - Rotate CAPTCHA
    - Click CAPTCHA
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.SIMPLE_CAPTCHA
        
    async def detect(self, page) -> bool:
        """Check if simple CAPTCHA is present"""
        # Generic CAPTCHA indicators
        selectors = [
            'img[src*="captcha"]',
            'img[alt*="captcha"]',
            '.captcha-image',
            '#captcha',
            'input[name*="captcha"]',
        ]
        
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve simple CAPTCHA
        
        Args:
            page: Playwright page
            challenge_element: CAPTCHA image or container
            **kwargs: Optional parameters
        """
        try:
            print("🔍 Solving simple CAPTCHA...")
            
            # Detect CAPTCHA type
            captcha_type = await self._detect_captcha_type(page)
            print(f"   Type: {captcha_type}")
            
            if captcha_type == "text":
                return await self._solve_text(page)
            elif captcha_type == "math":
                return await self._solve_math(page)
            elif captcha_type == "rotate":
                return await self._solve_rotate(page)
            elif captcha_type == "click":
                return await self._solve_click(page)
            else:
                print("⚠️ Unknown CAPTCHA type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving CAPTCHA: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _detect_captcha_type(self, page) -> str:
        """Detect which type of simple CAPTCHA"""
        
        # Text on image
        if await page.locator('img[src*="captcha"], .captcha-image img').count() > 0:
            # Check if there's a text input
            if await page.locator('input[name*="captcha"], input[placeholder*="captcha"]').count() > 0:
                # Check for math
                captcha_img = page.locator('img[src*="captcha"]').first
                alt = await captcha_img.get_attribute('alt')
                if alt and any(c in alt for c in ['+', '-', '*', '/']):
                    return "math"
                return "text"
                
        # Rotate CAPTCHA
        if await page.locator('.rotate-captcha, [class*="rotate"]').count() > 0:
            return "rotate"
            
        # Click CAPTCHA
        if await page.locator('.click-captcha, .point-captcha').count() > 0:
            return "click"
            
        return "unknown"
        
    async def _solve_text(self, page) -> bool:
        """Solve text CAPTCHA"""
        try:
            print("   Solving text CAPTCHA...")
            
            # Get CAPTCHA image
            captcha_img = page.locator('img[src*="captcha"], .captcha-image img')
            
            if await captcha_img.count() == 0:
                print("   ❌ CAPTCHA image not found")
                return False
                
            # Take screenshot
            screenshot = await captcha_img.first.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Store image temporarily
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    # Use qwen to read text
                    import subprocess
                    import re
                    
                    cmd = [
                        "qwen",
                        f"Read the text from this CAPTCHA image. Return ONLY the text you see, no explanations or quotes. Ignore any noise or lines: {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Extract text
                    text = result.stdout.strip()
                    # Clean up
                    text = re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', text)
                    
                    print(f"   Recognized text: {text}")
                    
                    if len(text) < 3:
                        print("   ⚠️ Text too short")
                        return False
                        
                    # Enter text
                    input_field = page.locator('input[name*="captcha"], input[placeholder*="captcha"]')
                    
                    if await input_field.count() > 0:
                        await input_field.fill(text)
                        
                        # Submit
                        submit_button = page.locator('button[type="submit"], input[type="submit"]')
                        if await submit_button.count() > 0:
                            await self.click_with_delay(submit_button)
                            
                        await asyncio.sleep(2)
                        print("✅ Text CAPTCHA solved!")
                        return True
                    else:
                        print("   ❌ Input field not found")
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
            
    async def _solve_math(self, page) -> bool:
        """Solve math CAPTCHA"""
        try:
            print("   Solving math CAPTCHA...")
            
            # Get CAPTCHA image
            captcha_img = page.locator('img[src*="captcha"]')
            
            if await captcha_img.count() == 0:
                print("   ❌ CAPTCHA image not found")
                return False
                
            # Take screenshot
            screenshot = await captcha_img.first.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Read the mathematical expression from this CAPTCHA image and calculate the result. Return ONLY the number, no explanation: {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Parse result
                    answer = result.stdout.strip()
                    # Extract number
                    import re
                    numbers = re.findall(r'-?\d+\.?\d*', answer)
                    
                    if numbers:
                        answer = numbers[0]
                    else:
                        print("   ⚠️ Could not parse answer")
                        return False
                        
                    print(f"   Calculated answer: {answer}")
                    
                    # Enter answer
                    input_field = page.locator('input[name*="captcha"], input[placeholder*="captcha"]')
                    
                    if await input_field.count() > 0:
                        await input_field.fill(str(answer))
                        
                        # Submit
                        submit_button = page.locator('button[type="submit"], input[type="submit"]')
                        if await submit_button.count() > 0:
                            await self.click_with_delay(submit_button)
                            
                        await asyncio.sleep(2)
                        print("✅ Math CAPTCHA solved!")
                        return True
                    else:
                        print("   ❌ Input field not found")
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
            
    async def _solve_rotate(self, page) -> bool:
        """Solve rotate CAPTCHA"""
        try:
            print("   Solving rotate CAPTCHA...")
            
            # Get rotate element
            rotate_elem = page.locator('.rotate-captcha img, .rotate-image')
            
            if await rotate_elem.count() == 0:
                print("   ❌ Rotate element not found")
                return False
                
            # Take screenshot
            screenshot = await rotate_elem.first.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this rotated image. What rotation angle (0-360) will make it upright? Return ONLY the angle number: {temp_path}",
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
                        print(f"   Rotation angle: {angle}°")
                    except:
                        print("   ⚠️ Could not parse angle")
                        angle = 90
                        
                    # Find rotation controls
                    rotate_left = page.locator('.rotate-left, [class*="rotate-left"]')
                    rotate_right = page.locator('.rotate-right, [class*="rotate-right"]')
                    
                    # Calculate clicks needed (assuming each click rotates 90°)
                    clicks = int(angle / 90) % 4
                    
                    # Click rotate button
                    if angle > 180:
                        # Rotate left
                        for _ in range(4 - clicks):
                            if await rotate_left.count() > 0:
                                await self.click_with_delay(rotate_left)
                                await asyncio.sleep(0.5)
                    else:
                        # Rotate right
                        for _ in range(clicks):
                            if await rotate_right.count() > 0:
                                await self.click_with_delay(rotate_right)
                                await asyncio.sleep(0.5)
                                
                    # Submit
                    submit_button = page.locator('button[type="submit"], .verify-button')
                    if await submit_button.count() > 0:
                        await self.click_with_delay(submit_button)
                        
                    await asyncio.sleep(2)
                    print("✅ Rotate CAPTCHA solved!")
                    return True
                    
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
            
    async def _solve_click(self, page) -> bool:
        """Solve click CAPTCHA (click specific points)"""
        try:
            print("   Solving click CAPTCHA...")
            
            # Get CAPTCHA image
            captcha_img = page.locator('.click-captcha img, .point-captcha img')
            
            if await captcha_img.count() == 0:
                print("   ❌ CAPTCHA image not found")
                return False
                
            # Take screenshot
            screenshot = await captcha_img.first.screenshot()
            
            # Get instruction
            instruction_elem = page.locator('.captcha-instruction, .click-instruction')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else "Click the correct points"
            print(f"   Instruction: {instruction}")
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this click CAPTCHA. {instruction}. Return coordinates as JSON array: [{{\"x\": 0-100, \"y\": 0-100}}, ...]: {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Parse coordinates
                    import json
                    try:
                        # Find JSON in response
                        import re
                        json_match = re.search(r'\[.*\]', result.stdout, re.DOTALL)
                        if json_match:
                            coords = json.loads(json_match.group(0))
                        else:
                            print("   ⚠️ No coordinates found")
                            return False
                            
                        print(f"   Clicking at: {coords}")
                        
                        # Get image box
                        img_box = await captcha_img.first.bounding_box()
                        if not img_box:
                            return False
                            
                        # Click at coordinates
                        for coord in coords:
                            x = img_box['x'] + (img_box['width'] * coord['x'] / 100)
                            y = img_box['y'] + (img_box['height'] * coord['y'] / 100)
                            
                            await page.mouse.click(x, y)
                            await asyncio.sleep(0.5)
                            
                        # Submit
                        submit_button = page.locator('button[type="submit"], .verify-button')
                        if await submit_button.count() > 0:
                            await self.click_with_delay(submit_button)
                            
                        await asyncio.sleep(2)
                        print("✅ Click CAPTCHA solved!")
                        return True
                        
                    except json.JSONDecodeError:
                        print("   ⚠️ Could not parse coordinates")
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