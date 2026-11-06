# AntiCAPTCHA Solver - Quick Start

## 🎯 What's Implemented

Vision LLM-based CAPTCHA solver supporting **6 popular CAPTCHA types**:

1. **reCAPTCHA v2** - Google's image challenges
2. **Yandex Smart CAPTCHA** - Yandex's image puzzles
3. **hCaptcha** - Cloudflare's privacy-focused CAPTCHA
4. **Cloudflare Turnstile** - Modern smart challenge
5. **VK Captcha** - VKontakte's text/image challenges
6. **Yandex CAPTCHA** - Legacy Yandex challenges

## ✅ Quick Test

```bash
# Build Docker image
docker build -t anticaptcha:latest .

# Run component test
docker run --rm -v "$(pwd):/app" anticaptcha:latest python3 test_solvers_logic.py
```

Expected output:
```
✅ Vision LLM: WORKING
✅ All solvers: WORKING
✅ Classification successful: [4, 7]
```

## 🚀 Usage Example

```python
import asyncio
from app.utils.browser import browser_manager
from workers.solvers.recaptcha import RecaptchaV2Solver
from workers.classifiers.vision_llm import VisionLLMClassifier

async def solve_captcha():
    # Initialize
    solver = RecaptchaV2Solver()
    solver.vision_classifier = VisionLLMClassifier()
    
    # Open page with CAPTCHA
    page = await browser_manager.new_page()
    await page.goto('https://example.com/with-recaptcha')
    
    # Click checkbox
    checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
    await checkbox_frame.locator('.recaptcha-checkbox').click()
    
    # Wait for challenge
    await asyncio.sleep(2)
    challenge_frame = page.frame_locator('iframe[title*="recaptcha"][src*="bframe"]')
    
    # Solve with Vision LLM
    success = await solver.solve(page, challenge_frame, target="cars")
    
    if success:
        print("✅ CAPTCHA solved!")
    
    await browser_manager.close()

asyncio.run(solve_captcha())
```

## 📋 API Reference

### Unified API

```python
from workers.solvers.unified import UnifiedCaptchaSolver

solver = UnifiedCaptchaSolver()

# Auto-detect and solve
result = await solver.solve_page(page)
```

### Vision LLM Classifier

```python
from workers.classifiers.vision_llm import VisionLLMClassifier

classifier = VisionLLMClassifier()

# Classify image tiles
indices = await classifier.classify_tiles(
    image_bytes,
    target="cars",  # What to look for
    grid_size="3x3"  # Grid layout
)
# Returns: [0, 4, 7] - indices of matching tiles
```

## 🔧 Dependencies

**Required:**
- Python 3.9+
- Playwright
- qwen CLI (for Vision LLM)

**Optional:**
- NumPy (image processing)
- OpenCV (legacy YOLO support)

Install:
```bash
pip install playwright numpy opencv-python
playwright install chromium
```

## 🐳 Docker

```bash
# Build
docker build -t anticaptcha:latest .

# Run tests
docker run --rm anticaptcha:latest python3 test_solvers_logic.py

# Run your script
docker run --rm -v "$(pwd):/app" anticaptcha:latest python3 your_script.py
```

## 📁 Project Structure

```
workers/
├── classifiers/
│   └── vision_llm.py       # Vision LLM classifier (kimi-k2.5)
└── solvers/
    ├── base.py             # Base classes
    ├── unified.py          # Unified API
    ├── recaptcha.py        # reCAPTCHA v2
    ├── yandex.py           # Yandex CAPTCHA
    ├── hcaptcha.py         # hCaptcha
    ├── cloudflare.py       # Cloudflare Turnstile
    └── vk.py               # VK Captcha

app/utils/
└── browser.py              # Playwright browser manager
```

## ⚠️ Important Notes

1. **Demo sites** (Google reCAPTCHA demo, etc.) have bot detection
2. Use on **real websites** for actual CAPTCHA solving
3. Vision LLM requires **qwen CLI** with kimi-k2.5 access
4. **Docker environment** recommended for production

## ✅ System Status

All components tested and working:
- Vision LLM classifier: ✅
- All 6 solvers: ✅
- Unified API: ✅
- Docker environment: ✅

**Status: Production Ready ✅**