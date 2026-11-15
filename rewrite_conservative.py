#!/usr/bin/env python3
"""Completely rewrite _solve_image_challenge_hybrid with conservative selection"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    lines = f.readlines()

# Find the method
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if 'async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:' in line:
        start_idx = i
    if start_idx and i > start_idx and line.strip().startswith('async def '):
        end_idx = i
        break

if start_idx and end_idx:
    # Replace the entire method
    new_method = '''    async def _solve_image_challenge_hybrid(self, page, challenge_frame, target: str) -> bool:
        """Solve using hybrid Yolo + heuristics approach with conservative selection"""
        print(f"🤖 Solving challenge (hybrid) for: {target}")

        # Get all image tiles
        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
        print(f"📸 Found {len(tiles)} images")

        # Collect candidates with confidence scores
        candidates = []  # List of (index, confidence)
        
        for i, tile in enumerate(tiles):
            img = tile.locator('img')

            # Take screenshot
            screenshot = await img.screenshot()

            # Classify and get confidence
            result = await self._classify_image_hybrid_with_confidence(screenshot, target)

            if result['should_select']:
                print(f"   Image {i+1}: ✅ CANDIDATE (conf: {result['confidence']:.2f})")
                candidates.append((i, result['confidence']))
            else:
                print(f"   Image {i+1}: ❌ Skip (max conf: {result['confidence']:.2f})")

        # CONSERVATIVE SELECTION: Select only top candidates
        if candidates:
            # Sort by confidence (highest first)
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            # Select only top 30% of candidates, minimum 1
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
                print(f"🎯 Selecting top {len(selected_indices)} candidates")
            
            # Click selected tiles
            for idx in selected_indices:
                tiles[idx].click()
                await asyncio.sleep(random.uniform(0.3, 0.7))
            
            print(f"✅ Selected {len(selected_indices)} images (conservative)")
            
            # Click verify
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return True
        
        else:
            # No candidates - click verify anyway
            print(f"⚠️ No candidates found, clicking verify...")
            verify_button = challenge_frame.locator('#recaptcha-verify-button')
            await verify_button.click()
            return False

    async def _classify_image_hybrid_with_confidence(self, image_bytes: bytes, target: str) -> dict:
        """Hybrid classification returning confidence score"""
        try:
            # Open image
            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)
            
            # COCO classes - use Yolo with reasonable confidence
            coco_targets = ['car', 'bus', 'truck', 'bicycle', 'motorcycle', 'traffic_light', 'fire_hydrant']
            
            if target in coco_targets and self.yolo_model:
                # Yolo detection
                results = self.yolo_model(img, verbose=False)
                
                if results and len(results) > 0:
                    boxes = results[0].boxes
                    
                    # Very high confidence threshold
                    MIN_CONFIDENCE = 0.80  # Very high to reduce false positives
                    
                    # Find highest confidence detection for target
                    max_conf = 0.0
                    found_target = False
                    
                    for box in boxes:
                        class_id = int(box.cls[0])
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf[0])
                        
                        # Check if this matches target (with relaxed mapping)
                        matches = False
                        if target == 'car' and class_name in ['car', 'truck', 'bus']:
                            matches = True
                        elif target == 'bus' and class_name in ['bus', 'truck']:
                            matches = True
                        elif target == 'truck' and class_name in ['truck', 'bus']:
                            matches = True
                        elif target == class_name:
                            matches = True
                        
                        if matches and confidence > MIN_CONFIDENCE:
                            found_target = True
                            max_conf = max(max_conf, confidence)
                    
                    return {
                        'should_select': found_target,
                        'confidence': max_conf
                    }
            
            # Heuristics for non-COCO classes
            elif target == 'crosswalk':
                result = self._detect_crosswalk(img_array)
                return {'should_select': result, 'confidence': 0.5 if result else 0.0}
            elif target == 'stairs':
                result = self._detect_stairs(img_array)
                return {'should_select': result, 'confidence': 0.5 if result else 0.0}
            
            return {'should_select': False, 'confidence': 0.0}
        
        except Exception as e:
            print(f"      ⚠️ Classification error: {e}")
            return {'should_select': False, 'confidence': 0.0}

'''
    
    # Replace
    lines[start_idx:end_idx] = [new_method]
    
    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.writelines(lines)
    
    print("✅ Rewrote _solve_image_challenge_hybrid with conservative selection")
    print(f"   - Old method: {end_idx - start_idx} lines")
    print(f"   - New method: {new_method.count(chr(10))} lines")
else:
    print("❌ Could not find method to replace")