# Limits and Constraints

**Last updated:** 2026-11-05

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
- **Auth:** API key in X-API-Key header
- **Max retries:** 3

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
- Passwords hashed with bcrypt
- No HTTPS (local network only)
- No rate limiting (trusted local user)