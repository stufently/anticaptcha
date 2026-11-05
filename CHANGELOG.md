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
- Скрипты запуска: run.sh, run_worker.py, init_db.py
- Учётные файлы: AGENTS.md, CHANGELOG.md, docs/STATE.md, docs/specs/limits.md
- Dockerfile.minimal для быстрого тестирования
- requirements-minimal.txt без тяжёлых ML зависимостей

### Fixed
- Исправлена ошибка SQLAlchemy relationships (добавлен ForeignKey)
- Заменён bcrypt на SHA-256 для хеширования паролей (совместимость с Docker)

### Security
- Хеширование API ключей (SHA-256)
- Хеширование паролей (SHA-256)
- Аутентификация через X-API-Key header

### Tested
- ✅ Все API endpoints протестированы и работают

## [1.0.0] - 2026-11-05

### Added
- Initial release
- FastAPI application structure
- Database models
- REST API
- Background worker
- CAPTCHA solvers