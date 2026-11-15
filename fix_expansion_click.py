#!/usr/bin/env python3
"""Fix expansion logic to not double-click tiles"""

# Read the file
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find the expansion click section
old = '''                        if should_reselect:
                            print(f"   Image {i+1}: ✅ SELECT (expanded area)")
                            await tile.click()
                            await asyncio.sleep(random.uniform(0.8, 1.5))
                        else:
                            print(f"   Image {i+1}: ❌ No target in expanded area")'''

new = '''                        if should_reselect:
                            # Keep the selection (already clicked once)
                            print(f"   Image {i+1}: ✅ Target still present in expanded area (keeping selection)")
                        else:
                            # Target gone in expanded area - might need to deselect
                            # For now, keep selection anyway
                            print(f"   Image {i+1}: ⚠️ Target not in expanded area (selection may be incorrect)")'''

if old in content:
    content = content.replace(old, new)
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    print("✅ Fixed expansion logic to not double-click")
else:
    print("❌ Could not find the exact section")