#!/usr/bin/env python3
"""Интеграция Vision LLM classifier в recaptcha.py"""

import sys
sys.path.insert(0, '/home/deploy/github/anticaptcha')

# Read current recaptcha.py
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'r') as f:
    content = f.read()

# Add import for vision classifier
if 'from workers.classifiers.vision_llm import' not in content:
    # Add after other imports
    content = content.replace(
        'from app.utils.captcha_solver import BaseSolver',
        'from app.utils.captcha_solver import BaseSolver\nfrom workers.classifiers.vision_llm import VisionLLMClassifier'
    )

# Add classifier instance to __init__
if 'self.vision_classifier' not in content:
    content = content.replace(
        '        self.yolo_model = None\n        self.custom_model = None',
        '        self.yolo_model = None\n        self.custom_model = None\n        self.vision_classifier = None'
    )

# Add initialization in setup
if 'self.vision_classifier = VisionLLMClassifier()' not in content:
    content = content.replace(
        '                print("✅ Yolo models loaded for reCAPTCHA")',
        '                print("✅ Yolo models loaded for reCAPTCHA")\n                \n                # Initialize vision classifier\n                self.vision_classifier = VisionLLMClassifier()\n                print("✅ Vision LLM classifier initialized")'
    )

# Save back
with open('/home/deploy/github/anticaptcha/workers/solvers/recaptcha.py', 'w') as f:
    f.write(content)

print("✅ Integrated Vision LLM classifier into recaptcha.py")
print("   - Added import")
print("   - Added instance variable")
print("   - Added initialization")