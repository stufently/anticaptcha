# Training Pipeline for reCAPTCHA Custom Model

## Overview

This document describes the complete pipeline for training a custom Yolo model on reCAPTCHA images.

## Problem

The pretrained Yolo model (yolov8n.pt) is trained on COCO dataset (normal photos), not synthetic reCAPTCHA images. This causes:
- False positives on reCAPTCHA tiles
- Low confidence scores
- Missed detections for reCAPTCHA-specific classes (crosswalk, stairs, etc.)

## Solution

Train custom model on real reCAPTCHA images collected from live challenges.

## Pipeline Steps

### 1. Collect Dataset

**Script:** `collect_recaptcha_dataset.py`

Collects images from Google reCAPTCHA demo:
- Navigates to reCAPTCHA demo
- Clicks checkbox to trigger challenge
- Extracts all image tiles from challenge
- Saves with metadata (target class, instruction, timestamp)

**Usage:**
```bash
python collect_recaptcha_dataset.py
```

**Output:**
- `data/recaptcha_dataset/images/` - Raw images
- `data/recaptcha_dataset/metadata.json` - Image metadata

**Goal:** 50+ challenges (400-900 individual images)

### 2. Auto-Annotate & Train

**Script:** `train_custom_yolo.py`

Two-step process:
1. **Auto-annotation**: For reCAPTCHA tiles, the entire image is the object, so we create full-image bounding boxes (class_id 0.5 0.5 1.0 1.0)
2. **Training**: Fine-tune Yolo model with transfer learning from pretrained weights

**Usage:**
```bash
python train_custom_yolo.py
```

**Output:**
- `data/recaptcha_dataset/yolo/` - YOLO format dataset
- `runs/detect/recaptcha_custom/weights/best.pt` - Trained model

### 3. Integrate Trained Model

Update `workers/solvers/recaptcha.py`:

```python
# Replace:
self.yolo_model = YOLO('yolov8n.pt')

# With:
self.yolo_model = YOLO('runs/detect/recaptcha_custom/weights/best.pt')
```

### 4. Test

**Script:** `test_multiple_sites.py`

Tests on multiple CAPTCHA sites:
- Google reCAPTCHA demo
- Alternative reCAPTCHA demo
- hCaptcha
- Cloudflare Turnstile

**Usage:**
```bash
python test_multiple_sites.py
```

## Architecture

```
collect_recaptcha_dataset.py
         ↓
    data/recaptcha_dataset/images/
         ↓
    train_custom_yolo.py
         ↓
    runs/detect/recaptcha_custom/weights/best.pt
         ↓
    workers/solvers/recaptcha.py
         ↓
    test_multiple_sites.py
```

## Classes Supported

### COCO Classes (pretrained Yolo)
- car, bus, truck
- bicycle, motorcycle
- traffic_light
- fire_hydrant

### reCAPTCHA-Specific Classes (need custom training)
- crosswalk
- stairs
- bridge
- mountain
- palm_tree
- chimney

## Expected Results

**Before custom training:**
- COCO classes: 70-80% accuracy
- Specific classes: 0-30% accuracy (heuristics unreliable)

**After custom training:**
- All classes: 85-95% accuracy
- Reduced false positives
- Better confidence scores

## Training Parameters

```python
EPOCHS = 100
IMG_SIZE = 640
BATCH_SIZE = 16
DEVICE = 'cpu'  # or 'cuda' if GPU available
```

## Troubleshooting

### Dataset collection fails
- Check internet connection
- Check reCAPTCHA demo is accessible
- Check Playwright/Chromium installed: `playwright install chromium`

### Training fails
- Check images collected: `ls data/recaptcha_dataset/images/`
- Check metadata exists: `cat data/recaptcha_dataset/metadata.json`
- Check classes balanced: `python -c "import json; print([x['target'] for x in json.load(open('data/recaptcha_dataset/metadata.json'))])"`

### Model not improving
- Collect more images (100+ challenges)
- Check class balance (equal distribution)
- Try different hyperparameters (learning rate, batch size)

## Docker Deployment

All scripts run in Docker container with all dependencies:

```bash
# Build
docker build -t anticaptcha:latest .

# Collect dataset
docker run --rm -v $(pwd)/data:/app/data anticaptcha:latest python collect_recaptcha_dataset.py

# Train model
docker run --rm -v $(pwd)/data:/app/data anticaptcha:latest python train_custom_yolo.py

# Test
docker run --rm anticaptcha:latest python test_multiple_sites.py
```

## Next Steps

1. ✅ Collect 50+ challenges
2. ✅ Auto-annotate with full-image boxes
3. ✅ Train custom model
4. ⏳ Integrate trained model into solver
5. ⏳ Test on real CAPTCHAs
6. ⏳ Measure success rate improvement
7. ⏳ Iterate: collect more data if needed

## References

- [Ultralytics YOLO Docs](https://docs.ultralytics.com/)
- [Playwright Stealth](https://github.com/AtuboDad/playwright_stealth)
- [COCO Dataset](https://cocodataset.org/)