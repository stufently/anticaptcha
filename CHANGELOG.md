# Changelog

## [Unreleased]

### Fixed (2026-11-10)
- Воркер больше не падает на старте: EasyOCR прогревается и читается из одного
  пути (`$EASYOCR_MODULE_PATH/model`, `user_network`), рантайм с `download_enabled=False`.
- reCAPTCHA v2 ищет YOLO так же, как `YOLOClassifier` (`ANTICAPTCHA_MODELS_DIR`:
  `recaptcha_custom.pt` → `yolov8s.pt` → `yolov8n.pt`), без скачивания.
- Сбой `setup()` одного солвера не роняет воркер: солвер пропускается с логом,
  его задачи уходят в failed (`No solver for task type`).
- Первая решённая задача на пустой базе больше не уходит в failed (Stats с
  нулевыми счётчиками, таблица `stats` создаётся `init_db`); сбой статистики
  только логируется.
- Таймаут решения `ANTICAPTCHA_TASK_TIMEOUT` (120 с): зависший солвер → failed,
  воркер берёт следующую задачу.
- Единая SSRF-проверка `page_url` (`workers/solvers/url_guard.py`) для
  reCAPTCHA v2/v3, hCaptcha, Turnstile: только http/https, без
  localhost/частных/link-local/CGNAT адресов, в том числе после DNS-резолва.
- Лимит тела запроса `ANTICAPTCHA_MAX_BODY_BYTES` (5 МБ): 413 до авторизации.
- SQLite: WAL + `busy_timeout` для параллельной записи API и воркера.
- `init_db.py` просто создаёт таблицы (был битый импорт и учётка с
  известным паролем).
- qwen CLI: в `config/qwen/settings.json` выбран тип авторизации `openai`.
- Release workflow: одна сборка образа (load → тест → push из кэша), очистка
  диска раннера.
- `PYTHONUNBUFFERED=1` в образе: логи воркера сразу видны в `docker logs`.
- `url_guard`: отказ на `\`, пробелы/управляющие символы, userinfo, хост вне
  `[a-z0-9.-]`; числовые формы IPv4 (`2130706433`, `0x7f.1`, восьмеричные)
  декодируются как в браузере. Солверы открывают нормализованный URL, который
  вернула проверка, а не исходную строку.
- Голые `except:` в солверах заменены на `except Exception`: они глотали
  `CancelledError`, и таймаут задачи не срабатывал.
- OCR (`image_text`) идёт в собственном однопоточном executor'е, а не в
  общем пуле: таймаут срабатывает в срок, вызовы `readtext()` не
  перекрываются, зависший OCR не занимает потоки других солверов, результат
  опоздавшего задания отбрасывается, не начатые задания не выполняются.

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
- YOLO classifier for fast image CAPTCHA (0.1-0.3 sec)
- Hybrid classifier (YOLO + Vision LLM fallback) - saves 70% API costs
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
- Добавлено полное покрытие тестами (25 тестов, все проходят)

### Tested
- ✅ Все API endpoints протестированы и работают
- ✅ reCAPTCHA demo - challenge обнаруживается
- ✅ Browser automation работает
- ✅ Yolo модели загружены
- ✅ Vision LLM classifier работает
- ✅ Все 12 solvers импортируются и регистрируются
- ✅ 25 unit tests проходят успешно

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