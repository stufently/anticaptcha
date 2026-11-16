# Project State

**Last updated:** 2026-11-16

## Current Status: ✅ Ready for Use

### Completed
- ✅ FastAPI infrastructure
- ✅ SQLite database with models
- ✅ REST API endpoints (all working)
- ✅ Background worker structure
- ✅ CAPTCHA solvers (structure ready)
- ✅ Docker configuration (minimal version tested)
- ✅ API documentation
- ✅ Tests (basic)

### Tested & Working
- ✅ Health check endpoint: `/health`
- ✅ Root endpoint: `/`
- ✅ User creation: `POST /api/v1/user`
- ✅ API key generation: `POST /api/v1/api-key/{user_id}`
- ✅ Task creation: `POST /api/v1/task`
- ✅ Task retrieval: `GET /api/v1/task/{id}`
- ✅ Statistics: `GET /api/v1/stats`

### Task types
`recaptcha_v2`, `recaptcha_v3`, `hcaptcha`, `image_text`, `turnstile`,
`yandex_smartcaptcha`, `slider` (`TaskType` in `app/schemas/task.py`, details and
limits per type — README, «Типы задач»).

### Pending (Optional)
- ⚠️ Test OCR with real CAPTCHA samples
- ⚠️ Create web dashboard

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

### ML Models (baked into the image)
- `/app/models/yolov8s.pt`, `/app/models/yolov8n.pt` — downloaded at build time,
  SHA-256 verified; an optional `recaptcha_custom.pt` in `ANTICAPTCHA_MODELS_DIR`
  takes priority (`workers/classifiers/yolo.py`). Nothing is downloaded at runtime.
- EasyOCR models — `/app/easyocr_models`, downloaded at build time.
- Vision LLM (reCAPTCHA v2 tiles, SmartCaptcha text task) — external, needs
  `BAILIAN_CODING_PLAN_API_KEY`.

## Configuration

All settings: `app/config.py` (environment variables with the `ANTICAPTCHA_`
prefix); `.env.example` lists a few of them.

## Deployment

API and worker are two processes from one image sharing the SQLite file:
README («Быстрый старт»), `DOCKER_COMPOSE.md`, Helm chart in `chart/`.

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