"""Amazon WAF CAPTCHA solver"""

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
        AMAZON_WAF = "amazon_waf"


class AmazonWAFSolver(BaseSolver):
    """
    Solver for Amazon WAF CAPTCHA
    
    Amazon WAF shows:
    - Simple image puzzles
    - Text-based challenges
    - Interactive puzzles
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.AMAZON_WAF
        
    async def detect(self, page) -> bool:
        """Check if Amazon WAF CAPTCHA is present"""
        selectors = [
            'div[id*="captchachallenge"]',
            'img[src*="captcha"]',
            '.cf-turnstile',  # Sometimes uses Cloudflare
            '#amazon-captcha',
        ]
        
        # Check URL
        if 'aws.amazon.com/captcha' in page.url or 'captcha' in page.url.lower():
            return True
            
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve Amazon WAF CAPTCHA
        
        Args:
            page: Playwright page
            challenge_element: CAPTCHA container
            **kwargs: Optional parameters
        """
        try:
            print("🔍 Solving Amazon WAF CAPTCHA...")
            
            # Detect challenge type
            challenge_type = await self._detect_challenge_type(page)
            print(f"   Type: {challenge_type}")
            
            if challenge_type == "image_text":
                return await self._solve_image_text(page)
            elif challenge_type == "puzzle":
                return await self._solve_puzzle(page)
            else:
                print("⚠️ Unknown challenge type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving Amazon WAF: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _detect_challenge_type(self, page) -> str:
        """Detect which type of Amazon WAF challenge"""
        
        # Image with text
        if await page.locator('img[src*="captcha"], #captcha-image').count() > 0:
            return "image_text"
            
        # Puzzle
        if await page.locator('.puzzle-container, [class*="puzzle"]').count() > 0:
            return "puzzle"
            
        return "unknown"
        
    async def _solve_image_text(self, page) -> bool:
        """Solve image with text CAPTCHA"""
        try:
            print("   Solving image text CAPTCHA...")
            
            # Get CAPTCHA image
            captcha_img = page.locator('img[src*="captcha"], #captcha-image')
            
            if await captcha_img.count() == 0:
                print("   ❌ CAPTCHA image not found")
                return False
                
            # Take screenshot
            screenshot = await captcha_img.screenshot()
            
            # Use OCR or Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Store image temporarily
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    # Use qwen to read text
                    import subprocess
                    import re
                    
                    cmd = [
                        "qwen",
                        f"Read the text from this CAPTCHA image. Return ONLY the text you see, no explanations or quotes: {temp_path}",
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
                    # Clean up - extract only alphanumeric
                    text = re.sub(r'[^a-zA-Z0-9]', '', text)
                    
                    print(f"   Recognized text: {text}")
                    
                    if len(text) < 3:
                        print("   ⚠️ Text too short")
                        return False
                        
                    # Enter text
                    input_field = page.locator('input[name*="captcha"], #captcha_response, #captchacharacters')
                    
                    if await input_field.count() > 0:
                        await input_field.fill(text)
                        
                        # Submit
                        submit_button = page.locator('button[type="submit"], input[type="submit"], #submit')
                        if await submit_button.count() > 0:
                            await self.click_with_delay(submit_button)
                            
                        await asyncio.sleep(2)
                        
                        # Check if solved
                        if 'captcha' not in page.url.lower():
                            print("✅ Amazon WAF solved!")
                            return True
                        else:
                            print("⚠️ Verification failed")
                            return False
                    else:
                        print("   ❌ Input field not found")
                        return False
                        
                finally:
                    import os
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_puzzle(self, page) -> bool:
        """Solve puzzle challenge"""
        try:
            print("   Solving puzzle challenge...")
            
            # Get puzzle elements
            puzzle_img = page.locator('.puzzle-image, .puzzle-bg')
            target_img = page.locator('.puzzle-piece, .puzzle-target')
            
            if await puzzle_img.count() == 0:
                print("   ❌ Puzzle image not found")
                return False
                
            # Take screenshot
            screenshot = await puzzle_img.screenshot()
            
            # Use Vision LLM to find position
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this puzzle CAPTCHA. Where should the piece be placed? Return X coordinate as percentage (0-100), no explanation: {temp_path}",
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
                        print(f"   Position: {x_percent}%")
                    except Exception:
                        print("   ⚠️ Could not parse position")
                        x_percent = 50
                        
                    # Get coordinates
                    puzzle_box = await puzzle_img.bounding_box()
                    if not puzzle_box:
                        return False
                        
                    target_x = puzzle_box['x'] + (puzzle_box['width'] * x_percent / 100)
                    
                    # Get slider
                    slider = page.locator('.puzzle-slider, .slider-button')
                    if await slider.count() == 0:
                        # Try drag from piece
                        piece = page.locator('.puzzle-piece')
                        if await piece.count() > 0:
                            piece_box = await piece.bounding_box()
                            if piece_box:
                                start_x = piece_box['x'] + piece_box['width'] / 2
                                start_y = piece_box['y'] + piece_box['height'] / 2
                                
                                # Perform drag
                                await page.mouse.move(start_x, start_y)
                                await page.mouse.down()
                                await asyncio.sleep(0.2)
                                
                                for i in range(10):
                                    curr_x = start_x + (target_x - start_x) * (i + 1) / 10
                                    await page.mouse.move(curr_x, start_y)
                                    await asyncio.sleep(0.05)
                                    
                                await page.mouse.up()
                                
                                await asyncio.sleep(2)
                                return True
                    else:
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
                        for i in range(15):
                            curr_x = start_x + distance * (i + 1) / 15
                            await page.mouse.move(curr_x, start_y)
                            await asyncio.sleep(0.05)
                            
                        await page.mouse.up()
                        
                        await asyncio.sleep(2)
                        
                        # Check
                        if 'captcha' not in page.url.lower():
                            print("✅ Puzzle solved!")
                            return True
                        else:
                            print("⚠️ Verification failed")
                            return False
                            
                finally:
                    import os
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
            else:
                print("⚠️ No vision classifier available")
                return False
                
        except Exception as e:
            print(f"   Error: {e}")
            return False