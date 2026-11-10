# Limits and Constraints

**Last updated:** 2026-11-10

## System Limits

### Throughput
- **Maximum tasks/hour:** 100
- **Concurrent tasks:** 1 (single worker)
- **Worker poll interval:** 1 second

### Resources
- **Minimum RAM:** 8 GB
- **Recommended RAM:** 16 GB
- **Minimum CPU:** 4 cores
- **GPU:** Optional (4GB+ VRAM recommended)
- **Disk space:** 5-10 GB (models + dependencies)

## Technical Constraints

### Browser (Playwright)
- **Timeout:** 30 seconds default
- **Headless mode:** Yes (no GUI)
- **Browser:** Chromium

### Database (SQLite)
- **File:** data/anticaptcha.db
- **Max size:** Limited by disk
- **Concurrent writes:** Single writer (SQLite limitation)

### API
- **Rate limit:** None (local service)
- **Auth:** `Authorization: Bearer <token>` — client API key for `/api/v1/task*`; admin token (`ANTICAPTCHA_ADMIN_TOKEN`) or an admin user's API key for `/api/v1/user` and `/api/v1/api-key/*`
- **Registration:** closed — users are created only by an admin (HTTP API or `python -m app.cli create-user`)
- **Max retries:** 3

### Client images (`image_text`)
- **Request body:** 5 MiB (`ANTICAPTCHA_MAX_BODY_BYTES`) — 413 before parsing
- **Max pixels:** 4 000 000 (`ANTICAPTCHA_MAX_IMAGE_PIXELS`)
- **Max side:** 4096 px (`ANTICAPTCHA_MAX_IMAGE_SIDE`)
- Checked from the header only (`PIL.Image.open` without `load()`) before
  `cv2.imdecode`, in `workers/solvers/image_text.py::check_image_dimensions`;
  equality passes, only a larger value is rejected
- Over limit → task `failed` with `Image too large: …`; unreadable header →
  `Unsupported or corrupt image: …`. Nothing is decoded in either case
- Why: a flat-colour 20000×20000 PNG is ~1.2 MB on the wire (it fits the body
  limit) but ~4.1 GB to decode and preprocess — enough for the OOM killer to
  take out a 4 GiB worker

### Worker liveness (heartbeat)
- **File:** `/tmp/worker-heartbeat` (`ANTICAPTCHA_WORKER_HEARTBEAT_FILE`,
  `worker.heartbeatFile` in the chart)
- **Interval:** 10 s (`ANTICAPTCHA_WORKER_HEARTBEAT_INTERVAL`), written from
  the worker's event loop after `setup_solvers()` and cancelled when `run()`
  exits; the write is atomic (temp file + `os.replace`)
- **Probe:** `python -m workers.heartbeat --check --max-age N` → rc 0 fresh,
  1 stale/missing/non-numeric
- **Chart:** `startupProbe` 10 s × 60 (600 s budget for model loading) and
  `livenessProbe` 30 s × 3 with `maxAgeSeconds: 300`, both removed by
  `worker.livenessProbe.enabled: false`
- `maxAgeSeconds` must stay above `ANTICAPTCHA_TASK_TIMEOUT` (120 s), otherwise
  a long solve looks like a dead worker

### ML Models
- **Yolo:** yolov8n-cls.pt (6 MB)
- **EasyOCR:** Auto-downloaded (~100 MB)

## CAPTCHA Limitations

### reCAPTCHA v2/v3
- Image challenges require Yolo model
- May not work on heavily protected sites
- Browser fingerprint detection possible

### hCaptcha
- Similar to reCAPTCHA
- Requires trained Yolo model for images

### Image-to-text
- OCR accuracy: 70-95% (depends on distortion)
- Works best on simple CAPTCHAs
- Complex distortion may fail

### Turnstile
- Usually solves automatically
- May fail on strict sites
- No ML model needed typically

## Scaling Limits

Current architecture is designed for **single user, local use**. For scaling:

1. **Queue system:** Add Redis/RabbitMQ for multiple workers
2. **Database:** Switch to PostgreSQL for concurrent access
3. **Workers:** Run multiple worker instances
4. **GPU:** Add GPU for faster ML inference

## Security Limits

- API keys stored as SHA-256 hashes
- Passwords hashed with salted SHA-256
- No HTTPS (local network only)
- No rate limiting (trusted local user)