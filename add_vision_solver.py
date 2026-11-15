#!/usr/bin/env python3
"""Add vision LLM solver for entire CAPTCHA challenge"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Add new method after _solve_image_challenge_hybrid
new_method = '''
    async def _solve_with_vision_llm(self, page, challenge_frame, target: str) -> bool:
        """
        Решает CAPTCHA с помощью одного вызова Vision LLM

        Подход конкурентов:
        1. Сделать screenshot всей CAPTCHA сетки
        2. Отправить в Vision LLM с инструкцией
        3. Получить индексы плиток для клика
        4. Кликнуть по этим плиткам

        Быстрее и точнее, чем YOLO!
        """
        print(f"🤖 Solving challenge with Vision LLM for: {target}")

        # Get challenge info
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        grid_size = len(tiles)
        print(f"📸 Found {grid_size} images")

        # Take screenshot of entire challenge
        try:
            challenge_screenshot = await challenge_frame.locator('.rc-imageselect-target').screenshot()
        except:
            # Fallback: take screenshot of first tile
            challenge_screenshot = await tiles[0].locator('img').screenshot()

        # Call vision LLM for classification
        if self.vision_classifier:
            try:
                grid_type = "3x3" if grid_size == 9 else "4x4" if grid_size == 16 else "2x3"
                instruction = f"Select all tiles with {target.replace('_', ' ')}"

                indices = await self.vision_classifier.classify_tiles(
                    challenge_screenshot,
                    instruction,
                    grid_type
                )

                print(f"🎯 Vision LLM selected {len(indices)} tiles: {indices}")

                # Click selected tiles
                for idx in indices:
                    if 0 <= idx < len(tiles):
                        print(f"   Clicking tile {idx}")
                        await tiles[idx].click()
                        await asyncio.sleep(random.uniform(0.3, 0.7))

                # Click verify button
                verify_button = challenge_frame.locator('#recaptcha-verify-button')
                await verify_button.click()

                return True

            except Exception as e:
                print(f"⚠️ Vision LLM failed: {e}")
                # Fall back to YOLO
                return await self._solve_image_challenge_hybrid(page, challenge_frame, target)
        else:
            print("⚠️ Vision classifier not initialized, using YOLO")
            return await self._solve_image_challenge_hybrid(page, challenge_frame, target)
'''

# Find where to insert (after _solve_image_challenge_hybrid)
if 'async def _solve_with_vision_llm' not in content:
    # Insert after _solve_image_challenge_hybrid definition
    # Find the end of the method
    import re

    # Find the next method after _solve_image_challenge_hybrid
    pattern = r'(async def _solve_image_challenge_hybrid.*?)(\n\n    def |\n    async def )'

    match = re.search(pattern, content, re.DOTALL)
    if match:
        insertion_point = match.end(1)
        content = content[:insertion_point] + new_method + content[insertion_point:]

        with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
            f.write(content)

        print("✅ Added vision LLM solver method")
    else:
        print("❌ Could not find insertion point")
else:
    print("⚠️ Vision LLM solver already exists")