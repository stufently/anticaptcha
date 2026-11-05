# Changelog

## [Unreleased]

### Added
- Базовая инфраструктура FastAPI с REST API
- База данных SQLite с моделями Task, User, APIKey, Stats
- Background worker для обработки задач
- Solvers для всех типов CAPTCHA:
  - reCAPTCHA v2/v3
  - hCaptcha
  - Image-to-text (OCR)
  - Cloudflare Turnstile
- Dockerfile для контейнеризации
- API документация (Swagger/ReDoc)
- Тесты для API endpoints

### Security
- Хеширование API ключей (SHA-256)
- Хеширование паролей (bcrypt)
- Аутентификация через X-API-Key header

## [1.0.0] - 2026-11-05

### Added
- Initial release
- FastAPI application structure
- Database models
- REST API
- Background worker
- CAPTCHA solvers