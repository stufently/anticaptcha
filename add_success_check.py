#!/usr/bin/env python3
"""Add better success detection after verification"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find the section where we check for new challenge
old = '''                        # Check for new challenge (multi-round)
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
                            pass'''

new = '''                        # Check if challenge frame is gone (success!)
                        try:
                            # If challenge frame is not visible, challenge is complete
                            challenge_visible = await challenge_frame.locator('.rc-imageselect-instructions').count()
                            if challenge_visible == 0:
                                print("✅ Challenge frame no longer visible!")
                                token = await self._extract_token(page)
                                if token:
                                    print(f"✅ Got token: {token[:50]}...")
                                    return {"token": token}
                        except:
                            # Challenge frame gone = success
                            print("✅ Challenge completed!")
                            token = await self._extract_token(page)
                            if token:
                                return {"token": token}

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
                            # Challenge frame might be gone
                            pass'''

if old in content:
    content = content.replace(old, new)
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Added better success detection")
else:
    print("❌ Could not find the exact section")