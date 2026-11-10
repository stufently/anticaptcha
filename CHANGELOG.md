# Changelog

## [Unreleased]

### Security
- Картинка клиента проверяется по заголовку до декода
  (`check_image_dimensions` в `workers/solvers/image_text.py`): при
  `width*height > ANTICAPTCHA_MAX_IMAGE_PIXELS` (4 000 000) или
  `max(width, height) > ANTICAPTCHA_MAX_IMAGE_SIDE` (4096) задача падает с
  `Image too large: …`, битый или нечитаемый заголовок — с
  `Unsupported or corrupt image`. Однотонный PNG 20000×20000 весит ~1,2 МБ
  (проходит лимит тела 5 МБ), а его декод и предобработка — ~4,1 ГБ: воркер с
  лимитом 4 GiB убивал OOM-killer.
- Vision LLM вызывается в песочнице: `--approval-mode plan`,
  `--max-tool-calls 0`, `--core-tools structured_output` и `--exclude-tools`
  из 13 имён (в том числе `tool_call`, через который достижимы субагенты,
  `web_fetch` и планировщик). Картинка уходит в запрос вложением
  (`@<путь>` + `--include-directories`), а не читается инструментом модели.
  Содержимое страницы контролирует атакующий, поэтому prompt injection больше
  не даёт ему инструментов агента. Режимы `auto`/`yolo` и переменная
  `QWEN_CODE_SUPPRESS_YOLO_WARNING` убраны.
- В `config/qwen/settings.json` выключены `memory.enableManagedAutoMemory` и
  `memory.enableManagedAutoDream`: CLI больше не делает второй запрос
  субагентом памяти с `write_file`/`edit` на враждебном контенте.
- Временная картинка `captcha_*.png` удаляется в `finally` при любом исходе
  (успех, падение, таймаут) — раньше файлы копились в `/tmp` воркера.
- Воркер больше не получает `ANTICAPTCHA_ADMIN_TOKEN`: запись отфильтрована из
  его env в чарте, добавлен ключ `worker.existingSecret` для отдельного Secret
  воркера (пусто — как раньше, общий `existingSecret`).
- Проверка размеров картинки принимает только форматы, которые Pillow и OpenCV
  читают одинаково (`ALLOWED_IMAGE_FORMATS` в `workers/solvers/image_text.py`:
  PNG, JPEG, WEBP, BMP); остальное — `Unsupported image format: <формат>`.
  У JPEG 2000 с двумя блоками `ihdr` Pillow берёт последний (32×32), а OpenJPEG
  внутри `cv2.imdecode` — первый (2500×2000): файл в 505 байт проходил лимиты и
  раздувался уже при декодировании.
- В `chart/README.md` и в комментарии у `worker.existingSecret` описана дыра
  фильтрации токена: фильтр `ANTICAPTCHA_ADMIN_TOKEN` действует только на список
  `env`, а при пустом `worker.existingSecret` воркер получает общий Secret
  целиком через `envFrom`, вместе с токеном.

### Added
- Heartbeat воркера (`workers/heartbeat.py`): `beat()` атомарно пишет метку
  времени (временный файл рядом + `os.replace`), `is_fresh()` проверяет возраст,
  `heartbeat_loop()` идёт из event loop воркера и переживает ошибки записи,
  CLI `python -m workers.heartbeat --check --max-age N [--path P]` — rc 0 свежий,
  1 иначе. Настройки: `ANTICAPTCHA_WORKER_HEARTBEAT_FILE`
  (`/tmp/worker-heartbeat`) и `ANTICAPTCHA_WORKER_HEARTBEAT_INTERVAL` (10 с).
- `startupProbe` и `livenessProbe` воркера в чарте по этому heartbeat:
  `worker.heartbeatFile`, `worker.livenessProbe.{enabled,maxAgeSeconds,periodSeconds,timeoutSeconds,failureThreshold}`,
  `worker.startupProbe.{periodSeconds,timeoutSeconds,failureThreshold}`;
  `enabled: false` убирает обе пробы.
- `BrowserManager` пересоздаёт мёртвый браузер: закэшированный, но отключённый
  (`is_connected()` ложен) сбрасывается вместе с контекстом, обработчик события
  `disconnected` чистит кэш (только для текущего браузера), драйвер
  переиспользуется, а сбой `chromium.launch` останавливает драйвер, чтобы
  следующий вызов поднял новый.
- `tests/test_m1_gaps.py` — 17 тестов на дыры, которые вскрыл независимый
  мутационный прогон M1 (11 из 28 мутантов выжили), и на дефекты D1/D2/J1/R/B.

### Fixed
- Воркер на свежем томе создаёт таблицы сам: `init_db()` первым шагом `run()`.
  Раньше при ещё не стартовавшем API воркер падал с `no such table: tasks`.
- Сбой `recover_interrupted_tasks()` больше не роняет воркер: пишется
  `⚠️ Recovery of interrupted tasks failed: <тип>: <текст>` и работа
  продолжается. Флаг `_recovery_pending` снимается только успехом, и цикл
  воркера повторяет попытку на каждой итерации — раньше ошибка восстановления
  глоталась навсегда, и задачи в `processing` висели до следующего рестарта.
- Версия берётся из `app.__version__` (`FastAPI(version=…)` и ответ `/`) и
  совпадает с `appVersion` чарта — 1.0.1; раньше в `app/main.py` было
  захардкожено 1.0.0.
- `PIL.Image.open` в процессе воркера подменён обёрткой ultralytics, которая
  глушит исходную ошибку и бросает `ModuleNotFoundError: No module named
  'pi_heif'` (и пытается поставить пакет в рантайме). Проверка размеров читает
  заголовок исходной функцией Pillow, поэтому бомба распознаётся как
  `Image too large:`, а не как `Unsupported or corrupt image`.
- `is_fresh()` в `workers/heartbeat.py` больше не считает свежей метку `inf`,
  `nan` или метку из далёкого будущего: возраст ограничен с двух сторон
  (`-max_age <= age <= max_age`), а будущая метка свежая только в пределах
  `max_age` (допуск на расхождение часов). Раньше условие `now - stamp <= max_age`
  выполнялось для любого `stamp >= now - max_age`, то есть метка из будущего
  вечно удовлетворяла liveness-пробу и зависший воркер не перезапускался.
- Vision LLM (`workers/classifiers/vision_llm.py`): при отмене корутины
  (`CancelledError` во время `process.communicate()`) дочерний процесс qwen
  теперь убивается, а после `kill()` на таймауте дожидается `wait()` — не
  остаётся ни живого процесса с картинкой атакующего, ни зомби.
- `BrowserManager.get_browser()` закрыт `asyncio.Lock`: два одновременных
  вызова больше не запускают каждый свой Chromium, и неудачный запуск не
  останавливает общий драйвер, убивая браузер соседа.

## [1.0.1] - 2026-11-10

### Fixed
- EasyOCR создаётся с `quantize=False` (рантайм и прогрев в Dockerfile):
  квантованный LSTM torch требует AVX2/FMA, на CPU без них (Ivy Bridge)
  воркер падал SIGILL (exit 132) на первой image_text задаче.
- Задачи, оставшиеся в `processing` после падения воркера, при его старте
  переводятся в failed («worker restarted while processing the task»), а не
  висят вечно; в pending не возвращаются, чтобы задача-убийца не зациклила
  crash-loop.
- `YOLO_CONFIG_DIR` в образе: Ultralytics больше не предупреждает о
  незаписываемом каталоге и не уходит в `/tmp`.

## [1.0.0] - 2026-11-10

### Fixed
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