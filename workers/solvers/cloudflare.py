"""Cloudflare Turnstile solver"""

import asyncio
import random
from typing import Dict, Any

# Import base solver
try:
    from workers.solvers.base import BaseSolver, CAPTCHAType
except ImportError:
    # Fallback for testing
    class BaseSolver:
        pass
    class CAPTCHAType:
        CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"


class CloudflareTurnstileSolver(BaseSolver):
    """
    Solver for Cloudflare Turnstile
    
    Turnstile is a behavioral CAPTCHA that typically:
    - Requires JavaScript execution
    - May show image challenges
    - Uses behavioral analysis
    """
    
    def __init__(self):
        super().__init__()
        self.type = CAPTCHAType.CLOUDFLARE_TURNSTILE
        
    async def detect(self, page) -> bool:
        """Check if Cloudflare Turnstile is present"""
        selectors = [
            'iframe[src*="turnstile"]',
            '.cf-turnstile',
            'div[data-sitekey]'
        ]
        
        for selector in selectors:
            if await page.locator(selector).count() > 0:
                return True
                
        return False
        
    async def solve(self, page, challenge_element, **kwargs) -> bool:
        """
        Solve Cloudflare Turnstile
        
        Turnstile usually auto-solves with JavaScript.
        May require manual interaction in some cases.
        """
        try:
            print("🔍 Solving Cloudflare Turnstile...")
            
            # Check if challenge is present
            turnstile_iframe = page.locator('iframe[src*="turnstile"]')
            
            if await turnstile_iframe.count() == 0:
                print("✅ Turnstile not found (may already be solved)")
                return True
                
            # Wait for auto-solve
            print("   Waiting for auto-solve (Turnstile uses behavioral analysis)...")
            
            # Turnstile typically auto-solves within a few seconds
            for i in range(10):
                await asyncio.sleep(1)
                
                # Check if solved
                if await turnstile_iframe.count() == 0:
                    print("✅ Turnstile auto-solved!")
                    return True
                    
            # If still not solved, try clicking
            print("   Auto-solve failed, trying manual interaction...")
            
            try:
                # Find and click the widget
                widget = page.locator('.cf-turnstile, .turnstile-widget')
                if await widget.count() > 0:
                    await self.click_with_delay(widget)
                    await asyncio.sleep(3)
                    
                    # Check if solved
                    if await turnstile_iframe.count() == 0:
                        print("✅ Turnstile solved with manual interaction")
                        return True
            except Exception as e:
                print(f"   Manual interaction failed: {e}")
                
            # Check for image challenge
            iframe = page.frame_locator('iframe[src*="turnstile"]')
            
            if await iframe.locator('img, .challenge-image').count() > 0:
                print("   Image challenge detected")
                
                # Use Vision LLM for image challenges
                if self.vision_classifier:
                    return await self._solve_image_challenge(iframe)
                else:
                    print("⚠️ No vision classifier for image challenge")
                    return False
                    
            print("❌ Turnstile could not be solved")
            return False
            
        except Exception as e:
            print(f"❌ Error solving Turnstile: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    async def _solve_image_challenge(self, iframe) -> bool:
        """Solve image challenge with Vision LLM"""
        try:
            # Get images
            images = await iframe.locator('.challenge-image, img').all()
            
            if not images:
                return False
                
            print(f"   Found {len(images)} images")
            
            # Take screenshot
            challenge_screenshot = await iframe.locator('.challenge-container, .task-grid').screenshot()
            
            # Use Vision LLM
            from workers.classifiers.vision_llm import VisionLLMClassifier
            classifier = self.vision_classifier if isinstance(self.vision_classifier, VisionLLMClassifier) else VisionLLMClassifier()
            
            # Get instruction
            instruction_elem = iframe.locator('.challenge-instruction, .prompt-text, h2')
            instruction = await instruction_elem.text_content() if await instruction_elem.count() > 0 else "Select matching tiles"
            
            # Determine grid size
            grid_size = "3x3" if len(images) == 9 else "4x4" if len(images) == 16 else "2x3"
            
            # Classify
            indices = await classifier.classify_tiles(
                challenge_screenshot,
                f"Select all tiles with {instruction}",
                grid_size
            )
            
            print(f"   Vision LLM selected: {indices}")
            
            # Click images
            for idx in indices:
                if 0 <= idx < len(images):
                    await self.click_with_delay(images[idx])
                    
            # Submit
            submit_button = iframe.locator('.challenge-submit, button[type="submit"]')
            if await submit_button.count() > 0:
                await self.click_with_delay(submit_button)
                
            print("✅ Image challenge solved")
            return True
            
        except Exception as e:
            print(f"   Error solving image challenge: {e}")
            return False