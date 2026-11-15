#!/usr/bin/env python3
"""Fix verify button logic to always click even when 0 images selected"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    lines = f.readlines()

# Find the section (around line 265-272)
# Replace the logic
for i, line in enumerate(lines):
    if 'if selected:' in line and 'Click verify' in lines[i+1]:
        # Found the section
        start = i
        end = i + 4  # The next 4 lines

        print(f"Found section at lines {i+1}-{i+5}")
        print("Old:")
        for j in range(start, min(end+1, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")

        # New code - always click verify
        new_code = '''        if selected:
            # Click verify
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True
        else:
            # No images selected - click verify anyway (no target objects)
            print("⚠️ No target objects found, clicking verify...")
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True
'''

        # Replace
        lines[start:end] = [new_code]

        # Write back
        with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
            f.writelines(lines)

        print("\nNew:")
        for j in range(start, min(start+11, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")

        print("\n✅ Updated verify button logic")
        break
else:
    print("❌ Could not find the section")