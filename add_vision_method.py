#!/usr/bin/env python3
"""Add vision LLM classification method"""

with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Find the _classify_image_hybrid_with_confidence method and add alternative
# Insert after the existing classification method

new_method = '''
    async def _classify_with_vision_llm(self, image_bytes: bytes, target: str, grid_size: int = 9) -> dict:
        """
        Классификация CAPTCHA с помощью Vision LLM (qw2)
        Альтернатива YOLO для более точного распознавания
        """
        try:
            if not self.vision_classifier:
                return {'should_select': False, 'confidence': 0.0, 'method': 'no_vision_llm'}

            # Determine grid type
            grid_type = "3x3" if grid_size == 9 else "4x4" if grid_size == 16 else "2x3"

            # Call vision classifier
            instruction = f"Select all tiles with {target.replace('_', ' ')}"
            indices = await self.vision_classifier.classify_tiles(
                image_bytes,
                instruction,
                grid_type
            )

            # Check if current tile should be selected
            # Note: This is for single tile classification
            # In grid context, would need different approach

            # For now, return confidence based on detection
            if indices:
                return {
                    'should_select': True,
                    'confidence': 0.85,  # High confidence for vision LLM
                    'method': 'vision_llm',
                    'all_indices': indices
                }
            else:
                return {
                    'should_select': False,
                    'confidence': 0.0,
                    'method': 'vision_llm'
                }

        except Exception as e:
            print(f"      ⚠️ Vision LLM error: {e}")
            return {'should_select': False, 'confidence': 0.0, 'method': 'vision_llm_error'}
'''

# Insert before _classify_image_hybrid_with_confidence
if 'async def _classify_with_vision_llm' not in content:
    # Find insertion point
    content = content.replace(
        '    async def _classify_image_hybrid_with_confidence',
        new_method + '\n    async def _classify_image_hybrid_with_confidence'
    )

    with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
        f.write(content)

    print("✅ Added vision LLM classification method")
else:
    print("⚠️ Vision LLM method already exists")