#!/usr/bin/env python3
"""Fix recaptcha.py to handle expanding tiles"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find the _solve_image_challenge_hybrid method
old_method = '''    async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:
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

        return False'''

new_method = '''    async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:
        """Solve using hybrid Yolo + heuristics approach"""
        print(f"🤖 Solving challenge (hybrid) for: {target}")

        # Get all image tiles
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        print(f"📸 Found {len(tiles)} images")

        # Track which tiles have been processed (to handle expansions)
        processed = set()
        selected = []
        
        # Process tiles, handling expansions
        i = 0
        while i < len(tiles):
            if i in processed:
                i += 1
                continue
                
            tile = tiles[i]
            img = tile.locator('img')

            # Take screenshot
            screenshot = await img.screenshot()

            # Classify with hybrid approach
            should_select = await self._classify_image_hybrid(screenshot, target)
            processed.add(i)

            if should_select:
                print(f"   Image {i+1}: ✅ SELECT")
                await tile.click()
                selected.append(i)
                await asyncio.sleep(random.uniform(0.8, 1.5))  # Wait for potential expansion
                
                # Check if tile expanded (new content appeared)
                try:
                    # Take new screenshot after expansion
                    new_screenshot = await img.screenshot()
                    
                    # If screenshot changed, re-classify
                    if new_screenshot != screenshot:
                        print(f"   Image {i+1}: 🔄 Tile expanded, re-classifying...")
                        should_reselect = await self._classify_image_hybrid(new_screenshot, target)
                        
                        if should_reselect:
                            print(f"   Image {i+1}: ✅ SELECT (expanded area)")
                            await tile.click()
                            await asyncio.sleep(random.uniform(0.8, 1.5))
                        else:
                            print(f"   Image {i+1}: ❌ No target in expanded area")
                except Exception as e:
                    # Tile might not have expanded, that's OK
                    pass
            else:
                print(f"   Image {i+1}: ❌ Skip")
            
            i += 1

        print(f"✅ Selected {len(selected)} images")

        if selected:
            # Click verify
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True

        return False'''

if old_method in content:
    content = content.replace(old_method, new_method)
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Successfully updated with expanding tile handling")
else:
    print("❌ Could not find the exact method to replace")
    print("\nSearching for method signature...")
    if "def _solve_image_challenge_hybrid" in content:
        print("✓ Found method signature")
    else:
        print("✗ NOT found method signature")