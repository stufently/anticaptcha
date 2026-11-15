#!/usr/bin/env python3
"""Adjust conservative strategy to be less aggressive"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find and adjust the selection logic
old_logic = '''            # Select only top 30% of candidates, minimum 1
            num_to_select = max(1, len(candidates) // 3)

            # Or if confidence gap is large, select only very confident ones
            high_conf_candidates = [c for c in candidates if c[1] > 0.80]

            if high_conf_candidates:
                # Use high confidence ones
                selected_indices = [c[0] for c in high_conf_candidates[:num_to_select]]
                print(f"🎯 Selecting {len(selected_indices)} HIGH-CONFIDENCE images (>{0.80:.2f})")
            else:
                # Use top candidates
                selected_indices = [c[0] for c in candidates[:num_to_select]]
                print(f"🎯 Selecting top {len(selected_indices)} candidates")'''

new_logic = '''            # Balanced selection: not too aggressive, not too conservative
            # Select top 50% of candidates, minimum 2, maximum 5
            num_to_select = min(5, max(2, len(candidates) // 2))

            # Also consider confidence threshold
            high_conf_candidates = [c for c in candidates if c[1] > 0.75]

            if high_conf_candidates and len(high_conf_candidates) >= 2:
                # Use high confidence ones, but at least 2 and at most 5
                selected_indices = [c[0] for c in high_conf_candidates[:min(5, max(2, len(high_conf_candidates)))]
                print(f"🎯 Selecting {len(selected_indices)} HIGH-CONFIDENCE images (>{0.75:.2f})")
            else:
                # Use top candidates, at least 2
                selected_indices = [c[0] for c in candidates[:num_to_select]]
                print(f"🎯 Selecting top {len(selected_indices)} candidates")'''

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    
    # Also lower confidence threshold
    content = content.replace('MIN_CONFIDENCE = 0.80  # Very high to reduce false positives', 
                             'MIN_CONFIDENCE = 0.75  # High but not too aggressive')
    
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)
    
    print("✅ Adjusted conservative strategy to be more balanced")
    print("   - Threshold: 0.80 -> 0.75")
    print("   - Selection: top 30% -> top 50%")
    print("   - Minimum: 1 -> 2")
else:
    print("❌ Could not find selection logic")