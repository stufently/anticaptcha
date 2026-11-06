"""VK Captcha solver"""

import asyncio
import random
import re
from typing import Dict, Any

# Import base solver
try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    # Fallback for testing
    class BaseSolver:
        pass
    class CAPTCHAType:
        VK_CAPTCHA = "vk_captcha"


class VKCaptchaSolver(BaseSolver):
    """
    Solver for VK Captcha
    
    VK Captcha typically shows:
    - Text recognition (letters/numbers)
    - Image puzzles
    - Slide puzzles
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.VK_CAPTCHA
        
    async def detect(self, page) -> bool:
        """Check if VK Captcha is present"""
        # VK-specific indicators
        selectors = [
            'img[src*="captcha"]',
            '.captcha_img',
            'input[name="captcha_key"]',
            '.vk_captcha',
        ]
        
        # Only detect if on VK domain
        is_vk = 'vk.com' in page.url or 'vk.ru' in page.url
        
        if not is_vk:
            return False
            
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve VK Captcha
        
        VK uses multiple CAPTCHA types:
        1. Text recognition (most common)
        2. Image puzzles
        3. Slide puzzles
        """
        try:
            print("🔍 Solving VK Captcha...")
            
            # Detect captcha type
            captcha_type = await self._detect_captcha_type(page)
            
            print(f"   Type: {captcha_type}")
            
            if captcha_type == "text":
                return await self._solve_text_captcha(page)
            elif captcha_type == "image":
                return await self._solve_image_captcha(page)
            elif captcha_type == "slide":
                return await self._solve_slide_captcha(page)
            else:
                print("❌ Unknown VK captcha type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving VK Captcha: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _detect_captcha_type(self, page) -> str:
        """Detect which type of VK Captcha is shown"""
        
        # Text captcha: image with distorted text
        if await page.locator('img[src*="captcha"][alt*="captcha"], .captcha_img img').count() > 0:
            # Check if there's an input field for text
            if await page.locator('input[name="captcha_key"], input[placeholder*="букв"]').count() > 0:
                return "text"
                
        # Image puzzle: multiple images to select
        if await page.locator('.captcha_puzzle, .captcha_images img').count() > 0:
            return "image"
            
        # Slide puzzle: slider element
        if await page.locator('.captcha_slider, input[type="range"]').count() > 0:
            return "slide"
            
        return "unknown"
        
    async def _solve_text_captcha(self, page) -> bool:
        """Solve text recognition captcha"""
        try:
            print("   Solving text captcha...")
            
            # Get captcha image
            captcha_img = page.locator('img[src*="captcha"], .captcha_img img')
            
            if await captcha_img.count() == 0:
                print("   ❌ Captcha image not found")
                return False
                
            # Take screenshot
            screenshot = await captcha_img.screenshot()
            
            # Use OCR or Vision LLM
            if self.vision_classifier:
                # Vision LLM approach
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # For text captcha, we need different approach
                # Store image temporarily
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    # Use qwen to read text
                    import subprocess
                    import json
                    
                    cmd = [
                        "qwen",
                        f"Read the text from this captcha image at {temp_path}. Return ONLY the text you see, no explanations.",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Extract text from response
                    text = result.stdout.strip()
                    
                    # Clean up - extract only alphanumeric
                    text = re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', text)
                    
                    print(f"   Recognized text: {text}")
                    
                    # Enter text
                    input_field = page.locator('input[name="captcha_key"], input[placeholder*="букв"]')
                    
                    if await input_field.count() > 0:
                        await input_field.fill(text)
                        
                        # Submit
                        submit_button = page.locator('button[type="submit"], .captcha_submit')
                        if await submit_button.count() > 0:
                            await self.click_with_delay(submit_button)
                            
                        print("✅ Text captcha solved")
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
                print("⚠️ No vision classifier available for text captcha")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_image_captcha(self, page) -> bool:
        """Solve image selection captcha"""
        try:
            print("   Solving image captcha...")
            
            # Similar to reCAPTCHA image challenge
            images = await page.locator('.captcha_images img, .captcha_puzzle img').all()
            
            if not images:
                print("   ❌ No images found")
                return False
                
            print(f"   Found {len(images)} images")
            
            # Get instruction
            instruction_elem = page.locator('.captcha_instruction, .captcha_text')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else "Select matching images"
            
            # Take screenshot
            screenshot = await page.locator('.captcha_container, .captcha_images').screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Determine grid
                grid_size = "3x3" if len(images) == 9 else "4x4" if len(images) == 16 else "2x3"
                
                # Classify
                indices = await classifier.classify_tiles(
                    screenshot,
                    f"Select all tiles with {instruction}",
                    grid_size
                )
                
                print(f"   Vision LLM selected: {indices}")
                
                # Click images
                for idx in indices:
                    if 0 <= idx < len(images):
                        await self.click_with_delay(images[idx])
                        
                # Submit
                submit_button = page.locator('.captcha_submit, button[type="submit"]')
                if await submit_button.count() > 0:
                    await self.click_with_delay(submit_button)
                    
                print("✅ Image captcha solved")
                return True
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_slide_captcha(self, page) -> bool:
        """Solve slide puzzle captcha"""
        try:
            print("   Solving slide captcha...")
            
            # VK slide captchas require dragging a slider
            # This is more complex and may need specific implementation
            
            slider = page.locator('.captcha_slider, input[type="range"]')
            
            if await slider.count() == 0:
                print("   ❌ Slider not found")
                return False
                
            # TODO: Implement slide puzzle solving
            # This requires:
            # 1. Analyzing the puzzle
            # 2. Determining correct position
            # 3. Dragging slider to position
            
            print("⚠️ Slide captcha not yet implemented")
            return False
            
        except Exception as e:
            print(f"   Error: {e}")
            return False