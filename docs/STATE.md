# Project State

**Last updated:** 2026-11-05

## Current Status: Development

### Completed
- ✅ FastAPI infrastructure
- ✅ SQLite database with models
- ✅ REST API endpoints
- ✅ Background worker
- ✅ CAPTCHA solvers structure
- ✅ Docker configuration
- ✅ API documentation

### In Progress
- ⚠️ ML models need to be downloaded/trained

### Pending
- ❌ Download Yolo models for image classification
- ❌ Test OCR with real CAPTCHA samples
- ❌ Add comprehensive error handling
- ❌ Create web dashboard (optional)

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Client    │────>│  FastAPI     │────>│   SQLite    │
└─────────────┘     │  REST API    │     │  Database   │
                    └──────────────┘     └─────────────┘
                           │
                           v
                    ┌──────────────┐
                    │   Worker     │
                    │   Process    │
                    └──────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        v                  v                  v
  ┌──────────┐      ┌──────────┐      ┌──────────┐
  │ Browser  │      │   Yolo   │      │  EasyOCR │
  │Automation│      │  Model   │      │   Model  │
  └──────────┘      └──────────┘      └──────────┘
```

## Components

### API Server (app/)
- main.py - FastAPI application
- api/ - REST endpoints
- models/ - SQLAlchemy models
- schemas/ - Pydantic schemas

### Worker (workers/)
- task_worker.py - Background processor
- solvers/ - CAPTCHA solvers

### ML Models (models/)
- yolov8n-cls.pt - Image classification (needs download)
- OCR models - Auto-downloaded by EasyOCR

## Configuration

See .env.example for all settings.

## Deployment

```bash
docker build -t anticaptcha .
docker run -d -p 8000:8000 anticaptcha
```

## Known Issues

1. Image challenges in reCAPTCHA/hCaptcha require trained Yolo model
2. Turnstile may not always solve automatically
3. OCR accuracy depends on CAPTCHA distortion level

## Performance

Expected solve times:
- reCAPTCHA v2: 10-30 seconds
- hCaptcha: 10-30 seconds
- Image-to-text: 1-5 seconds
- Turnstile: 5-15 seconds