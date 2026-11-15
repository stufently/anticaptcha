#!/usr/bin/env python3
"""Fix recaptcha.py to handle multi-round challenges"""

import re

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find and replace the section
old_section = '''print(f"🎯 Target: {target}")

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

            raise RuntimeError("Could not solve image challenge")'''

new_section = '''print(f"🎯 Target: {target}")

            # Solve image challenge with hybrid approach
            if self.yolo_model or HAS_ML:
                # Handle multi-round challenges (max 5 rounds)
                max_rounds = 5
                for round_num in range(1, max_rounds + 1):
                    print(f"\\n🔄 Round {round_num}/{max_rounds}")
                    
                    result = await self._solve_image_challenge_hybrid(page, challenge_frame, target)
                    
                    if result:
                        # Wait for verification
                        await asyncio.sleep(2)
                        
                        # Check for token (success)
                        token = await self._extract_token(page)
                        if token:
                            print(f"✅ Challenge solved! Token: {token[:50]}...")
                            return {"token": token}
                        
                        # Check for success indicator (green checkmark)
                        try:
                            checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
                            checkbox_checked = await checkbox_frame.locator('#recaptcha-anchor.recaptcha-checkbox-checked').count()
                            if checkbox_checked > 0:
                                print("✅ Checkbox marked as verified!")
                                token = await self._extract_token(page)
                                if token:
                                    print(f"✅ Token: {token[:50]}...")
                                    return {"token": token}
                        except:
                            pass
                        
                        # Check for new challenge (multi-round)
                        try:
                            new_tiles = await challenge_frame.locator('.rc-image-tile-wrapper').count()
                            if new_tiles > 0:
                                # New images appeared - continue to next round
                                print("🔄 New images detected, continuing...")
                                
                                # Re-read instruction (might change)
                                try:
                                    new_instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
                                    new_target = self._extract_target(new_instruction)
                                    if new_target and new_target != target:
                                        print(f"🎯 Target changed: {new_target}")
                                        target = new_target
                                except:
                                    pass
                                
                                continue
                        except:
                            pass
                        
                        # Check for error message
                        try:
                            error_elem = await challenge_frame.locator('.rc-imageselect-error').count()
                            if error_elem > 0:
                                print("❌ reCAPTCHA reported error")
                                break
                        except:
                            pass
                        
                        # No new images, no token, no error - might be timing
                        print("⚠️ Verification status unclear")
                        await asyncio.sleep(1)
                        token = await self._extract_token(page)
                        if token:
                            return {"token": token}

            raise RuntimeError("Could not solve image challenge")'''

if old_section in content:
    content = content.replace(old_section, new_section)
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Successfully updated recaptcha.py")
else:
    print("❌ Could not find the section to replace")
    print("\nSearching for key phrases...")
    if "🎯 Target:" in content:
        print("✓ Found '🎯 Target:' marker")
    else:
        print("✗ NOT found '🎯 Target:' marker")
    
    if "Could not solve image challenge" in content:
        print("✓ Found 'Could not solve image challenge'")
    else:
        print("✗ NOT found 'Could not solve image challenge'")