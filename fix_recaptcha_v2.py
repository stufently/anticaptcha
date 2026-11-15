#!/usr/bin/env python3
"""Fix recaptcha.py to handle multi-round challenges"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Old section (lines 107-122 from the analysis)
old_section = '''            print(f"🎯 Target: {target}")
            
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

# New section with multi-round handling
new_section = '''            print(f"🎯 Target: {target}")
            
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
    print("✅ Successfully updated recaptcha.py with multi-round handling")
else:
    print("❌ Could not find the exact section to replace")
    print(f"\nSearching in {len(content)} chars of content...")
    print(f"Old section length: {len(old_section)} chars")
    print(f"Looking for unique substring: '{old_section[50:100]}'")
    
    if old_section[50:100] in content:
        print("✓ Found the unique substring")
        # Try to find where the difference is
        for i in range(min(len(old_section), 200)):
            if i < len(content):
                if old_section[i] != content[content.find(old_section[50:100]) - 50 + i]:
                    print(f"✗ First difference at position {i}:")
                    print(f"  Expected: {repr(old_section[max(0,i-10):i+10])}")
                    print(f"  Got: {repr(content[content.find(old_section[50:100]) - 50 + max(0,i-10):content.find(old_section[50:100]) - 50 + i+10])}")
                    break
    else:
        print("✗ NOT found the unique substring")