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
  - **FunCaptcha (Arkose Labs)** - rotate/drag/select challenges
  - **GeeTest** - slide/icon/nine-grid puzzles
  - **Amazon WAF** - image text and puzzle challenges
  - **Tencent CAPTCHA (TenDI)** - slide/select/click verification
  - **Simple CAPTCHA** - text/math/rotate/click challenges
  - **Yandex CAPTCHA/SmartCaptcha** - full implementation
  - **VK Captcha** - text/image/slide puzzles
- Vision LLM classifier (kimi-k2.5) for all image-based CAPTCHAs
- Unified API для всех типов CAPTCHA
- Dockerfile для контейнеризации
- API документация (Swagger/ReDoc)
- Тесты для API endpoints
- Скрипты запуска: run.sh, run_worker.py, init_db.py
- Учётные файлы: AGENTS.md, CHANGELOG.md, docs/STATE.md, docs/specs/limits.md
- Dockerfile.minimal для быстрого тестирования
- requirements-minimal.txt без тяжёлых ML зависимостей
- Ленивая загрузка ML зависимостей в solvers
- Тестовые скрипты для реальных CAPTCHA
- TEST_REPORT.md с результатами тестирования
- CAPTCHA_SUPPORT.md - сравнение с конкурентами (RuCaptcha, Anti-Captcha, CapMonster)
- README_SOLVER.md - quick start guide

### Fixed
- Исправлена ошибка SQLAlchemy relationships (добавлен ForeignKey)
- Заменён bcrypt на SHA-256 для хеширования паролей (совместимость с Docker)
- Ленивый импорт cv2/numpy для работы без ML моделей
- Исправлен детектор CAPTCHA: async wait_for для iframes, case-insensitive селекторы
- Исправлено извлечение site_key для reCAPTCHA из страницы
- Унифицирован интерфейс solve() для разных типов solvers

### Security
- Хеширование API ключей (SHA-256)
- Хеширование паролей (SHA-256)
- Аутентификация через X-API-Key header

### Tested
- ✅ Все API endpoints протестированы и работают
- ✅ reCAPTCHA demo - challenge обнаруживается
- ✅ Browser automation работает
- ✅ Yolo модели загружены
- ⚠️ Real sites block automation (bot detection)

## [1.0.0] - 2026-11-05

### Added
- Initial release
- FastAPI application structure
- Database models
- REST API
- Background worker
- CAPTCHA solvers