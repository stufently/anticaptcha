"""GeeTest CAPTCHA solver"""

import asyncio
import json
import random
import re
from typing import Dict, Any, Optional, List

try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    class BaseSolver:
        pass
    class CAPTCHAType:
        GEETEST = "geetest"


class GeeTestSolver(BaseSolver):
    """
    Solver for GeeTest CAPTCHA
    
    GeeTest shows:
    - Slide puzzle (drag piece to correct position)
    - Icon selection (select matching icons)
    - Nine-grid puzzle (select tiles in order)
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.GEETEST
        
    async def detect(self, page) -> bool:
        """Check if GeeTest is present"""
        selectors = [
            'iframe[src*="geetest"]',
            '.geetest-panel',
            '#geetest',
            'div[class*="geetest"]',
        ]
        
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve GeeTest CAPTCHA
        
        Args:
            page: Playwright page
            challenge_element: GeeTest container
            **kwargs: Optional parameters
        """
        try:
            print("🔍 Solving GeeTest...")
            
            # Detect challenge type
            challenge_type = await self._detect_challenge_type(page)
            print(f"   Type: {challenge_type}")
            
            if challenge_type == "slide":
                return await self._solve_slide(page)
            elif challenge_type == "icon":
                return await self._solve_icon(page)
            elif challenge_type == "nine":
                return await self._solve_nine_grid(page)
            else:
                print("❌ Unknown GeeTest type")
                return False
                
        except Exception as e:
            print(f"❌ Error solving GeeTest: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _detect_challenge_type(self, page) -> str:
        """Detect which type of GeeTest challenge"""
        
        # Slide puzzle
        if await page.locator('.geetest-slider, .geetest-slider-tip').count() > 0:
            return "slide"
            
        # Icon selection
        if await page.locator('.geetest-icon, .geetest-table-img').count() > 0:
            return "icon"
            
        # Nine-grid
        if await page.locator('.geetest-item-img, .geetest-task').count() > 0:
            return "nine"
            
        return "unknown"
        
    async def _solve_slide(self, page) -> bool:
        """Solve slide puzzle - drag piece to correct position"""
        try:
            print("   Solving slide puzzle...")
            
            # Wait for images to load
            await asyncio.sleep(1)
            
            # Get background and slider images
            bg_img = page.locator('.geetest_canvas_bg, .geetest-bg')
            slider_img = page.locator('.geetest_canvas_slice, .geetest-slider-img')
            
            if await bg_img.count() == 0:
                print("   ❌ Background image not found")
                return False
                
            # Get screenshots
            bg_screenshot = await bg_img.screenshot()
            
            # Get slider button
            slider_button = page.locator('.geetest-slider-button, .geetest-btn')
            
            if await slider_button.count() == 0:
                print("   ❌ Slider button not found")
                return False
                
            # Use Vision LLM to detect position
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Ask for x position
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(bg_screenshot)
                    temp_path = f.name
                    
                try:
                    import subprocess
                    cmd = [
                        "qwen",
                        f"Analyze this GeeTest slide puzzle background. The missing piece should be dragged to fill the gap. What is the X coordinate (0-1000) where the gap is located? Return ONLY a number, no explanation: {temp_path}",
                        "--approval-mode", "auto",
                        "--max-wall-time", "30s"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=45
                    )
                    
                    # Parse x position
                    try:
                        x_percent = float(result.stdout.strip())
                        print(f"   Detected gap at {x_percent}%")
                    except:
                        print("   ⚠️ Could not parse position, trying random")
                        x_percent = random.randint(30, 70)
                        
                    # Get actual coordinates
                    bg_box = await bg_img.bounding_box()
                    if not bg_box:
                        return False
                        
                    target_x = bg_box['x'] + (bg_box['width'] * x_percent / 100)
                    
                    # Perform drag
                    button_box = await slider_button.bounding_box()
                    if not button_box:
                        return False
                        
                    start_x = button_box['x'] + button_box['width'] / 2
                    start_y = button_box['y'] + button_box['height'] / 2
                    
                    # Calculate distance
                    distance = target_x - start_x
                    
                    # Perform drag with human-like movement
                    await page.mouse.move(start_x, start_y)
                    await asyncio.sleep(0.1)
                    await page.mouse.down()
                    await asyncio.sleep(0.2)
                    
                    # Move gradually with some randomness
                    steps = 20
                    for i in range(steps):
                        progress = (i + 1) / steps
                        curr_x = start_x + distance * progress
                        # Add slight vertical variation
                        curr_y = start_y + random.uniform(-2, 2)
                        await page.mouse.move(curr_x, curr_y)
                        await asyncio.sleep(random.uniform(0.01, 0.05))
                        
                    await asyncio.sleep(0.1)
                    await page.mouse.up()
                    
                    # Wait for verification
                    await asyncio.sleep(2)
                    
                    # Check if solved
                    success_indicator = page.locator('.geetest-success, .geetest-result-success')
                    if await success_indicator.count() > 0:
                        print("✅ Slide puzzle solved!")
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
                # Try random position
                return await self._try_random_slide(page, slider_button)
                
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _try_random_slide(self, page, slider_button) -> bool:
        """Try random sliding positions"""
        try:
            button_box = await slider_button.bounding_box()
            if not button_box:
                return False
                
            start_x = button_box['x'] + button_box['width'] / 2
            start_y = button_box['y'] + button_box['height'] / 2
            
            # Try a few positions
            for _ in range(3):
                distance = random.randint(100, 300)
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                await asyncio.sleep(0.2)
                
                for i in range(10):
                    curr_x = start_x + distance * (i + 1) / 10
                    await page.mouse.move(curr_x, start_y)
                    await asyncio.sleep(0.05)
                    
                await page.mouse.up()
                await asyncio.sleep(1)
                
                # Check
                if await page.locator('.geetest-success').count() > 0:
                    return True
                    
            return False
            
        except Exception as e:
            print(f"   Error: {e}")
            return False
            
    async def _solve_icon(self, page) -> bool:
        """Solve icon selection - select matching icons"""
        try:
            print("   Solving icon selection...")
            
            # Get instruction
            instruction_elem = page.locator('.geetest-tip, .geetest-desc')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else "Select matching icons"
            print(f"   Instruction: {instruction}")
            
            # Get icons
            icons = await page.locator('.geetest-icon, .geetest-table-img').all()
            
            if not icons:
                print("   ❌ No icons found")
                return False
                
            print(f"   Found {len(icons)} icons")
            
            # Take screenshot
            container = page.locator('.geetest-table, .geetest-panel')
            screenshot = await container.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # Determine grid
                grid_size = f"{len(icons) // 3}x3" if len(icons) % 3 == 0 else f"{len(icons)}"
                
                # Classify
                indices = await classifier.classify_tiles(
                    screenshot,
                    instruction,
                    grid_size
                )
                
                print(f"   Vision LLM selected: {indices}")
                
                # Click icons
                for idx in indices:
                    if 0 <= idx < len(icons):
                        await self.click_with_delay(icons[idx])
                        await asyncio.sleep(0.3)
                        
                # Submit
                submit_button = page.locator('.geetest-submit, .geetest-btn')
                if await submit_button.count() > 0:
                    await self.click_with_delay(submit_button)
                    
                await asyncio.sleep(2)
                
                # Check
                if await page.locator('.geetest-success').count() > 0:
                    print("✅ Icon selection solved!")
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
            
    async def _solve_nine_grid(self, page) -> bool:
        """Solve nine-grid puzzle - select tiles in specific order"""
        try:
            print("   Solving nine-grid puzzle...")
            
            # Get instruction
            instruction_elem = page.locator('.geetest-task-desc, .geetest-tip')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else ""
            print(f"   Instruction: {instruction}")
            
            # Get tiles
            tiles = await page.locator('.geetest-item-img, .geetest-task-item').all()
            
            if not tiles:
                print("   ❌ No tiles found")
                return False
                
            print(f"   Found {len(tiles)} tiles")
            
            # Take screenshot
            container = page.locator('.geetest-task-table, .geetest-panel')
            screenshot = await container.screenshot()
            
            # Use Vision LLM
            if self.vision_classifier:
                from workers.classifiers.vision_llm import VisionLLMClassifier
                classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
                
                # For nine-grid, need to select in ORDER
                indices = await classifier.classify_tiles(
                    screenshot,
                    instruction,
                    "3x3"
                )
                
                print(f"   Vision LLM selected in order: {indices}")
                
                # Click tiles in order
                for idx in indices:
                    if 0 <= idx < len(tiles):
                        await self.click_with_delay(tiles[idx])
                        await asyncio.sleep(0.5)
                        
                # Submit
                submit_button = page.locator('.geetest-submit, .geetest-btn')
                if await submit_button.count() > 0:
                    await self.click_with_delay(submit_button)
                    
                await asyncio.sleep(2)
                
                # Check
                if await page.locator('.geetest-success').count() > 0:
                    print("✅ Nine-grid solved!")
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