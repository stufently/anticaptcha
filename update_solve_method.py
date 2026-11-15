#!/usr/bin/env python3
"""Update solve method to use vision LLM"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find where _solve_image_challenge_hybrid is called in the main solve flow
# and replace with _solve_with_vision_llm

# Replace the call
if 'result = await self._solve_image_challenge_hybrid(page, challenge_frame, target)' in content:
    content = content.replace(
        'result = await self._solve_image_challenge_hybrid(page, challenge_frame, target)',
        'result = await self._solve_with_vision_llm(page, challenge_frame, target)  # Use Vision LLM instead of YOLO'
    )

    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)

    print("✅ Updated solve method to use Vision LLM")
    print("   Changed: _solve_image_challenge_hybrid → _solve_with_vision_llm")
else:
    print("⚠️ Could not find the call to replace")
    print("   Vision LLM will be used as fallback in _solve_with_vision_llm")