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
- Playwright 1.40.0 → 1.65.0, то есть Chromium 120.0.6099.28 (ноябрь 2023) →
  158.0.8127.18. Песочницу в нашем запуске включить нельзя: дефолтный seccomp
  docker режет unprivileged user namespaces (`FATAL … No usable sandbox!`),
  setuid-помощник `chrome_sandbox` без root не работает
  (`Zygote process exited prematurely with exit code 82`, а с
  `no-new-privileges` — `not running as root`), а `--no-zygote` с включённой
  песочницей отвергается самим Chromium. Значит `--no-sandbox` остаётся, и
  эксплойт рендерера на странице клиента даёт код в воркере от uid 1000 —
  единственная доступная защита здесь держать Chromium свежим. Обоснование
  комментарием в `app/utils/browser.py` и в `docs/specs/limits.md`.
- В образе выключена авто-установка пакетов ultralytics
  (`ENV YOLO_AUTOINSTALL=false`). ultralytics подменяет `PIL.Image.open` и при
  ЛЮБОЙ ошибке открытия зовёт `check_requirements("pi-heif")`: с сетью это
  установка чужого кода через pip от uid 1000 во время обработки задачи.
  `pi-heif` в образ НЕ добавлен — HEIF не входит в `ALLOWED_IMAGE_FORMATS`
  (PNG/JPEG/WEBP/BMP) и клиенту не нужен.

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
- Квота активных задач на API-ключ: `POST /api/v1/task` считает задачи этого
  ключа в статусах `pending`/`processing` одним SQL `COUNT` и при достижении
  лимита отдаёт 429 `Too many active tasks for this API key: limit is N`.
  Замок пишущего (`BEGIN IMMEDIATE` на соединении сессии) берётся ДО подсчёта:
  без него одновременные запросы все читают старое число и все вставляют
  (замер: 5 строк при лимите 1). Настройка
  `ANTICAPTCHA_MAX_ACTIVE_TASKS_PER_KEY` (20; 0 = без лимита), читается на
  каждый запрос.
- Чистка базы по срокам хранения (`workers/cleanup.py`): `purge_tasks()`
  батчами не больше `batch_size` (100) строк, каждый со своим commit, сначала
  удаляет задачи `solved`/`failed` старше `ANTICAPTCHA_TASK_RETENTION_DAYS` (7),
  затем обнуляет `input_data` (до 5 МБ base64 на задачу) у `solved`/`failed`
  старше `ANTICAPTCHA_INPUT_RETENTION_HOURS` (1); сравнение возраста строгое,
  `pending`/`processing`, `result`, `error_message` и таблица `stats` не
  трогаются. Пустой `input_data` — признак «вход вычищен»: API не может создать
  задачу с `""` (`json.dumps` даёт минимум `{}`), а воркер разбирает вход только
  у задачи, взятой из pending. `reclaim_space()` мигрирует старую базу
  (`auto_vacuum != 2`) в INCREMENTAL одним полным `VACUUM`, а уже мигрированную
  освобождает `incremental_vacuum` до пустого freelist и усекает `-wal`
  (`wal_checkpoint(TRUNCATE)`) — иначе бэкап, копирующий файл базы, всё равно
  видит прежний размер. `run_cleanup()` = purge, затем reclaim.
- Воркер зовёт чистку сам: `TaskWorker.maybe_cleanup()` в цикле опроса, первый
  раз сразу (после восстановления прерванных задач), дальше раз в
  `ANTICAPTCHA_CLEANUP_INTERVAL_SECONDS` (600) по `time.monotonic()`, запуск
  через `asyncio.to_thread` — синхронный `VACUUM` в потоке event loop остановил
  бы heartbeat, и liveness-проба убила бы под посреди VACUUM. Сбой чистки
  логируется и не пробрасывается, интервал отсчитывается и от неудачного запуска.
- `PRAGMA auto_vacuum=INCREMENTAL` в слушателе `connect` (`app/database.py`)
  ПЕРЕД `journal_mode=WAL`: в обратном порядке новая база создаётся с
  `auto_vacuum=0` (замер на sqlite 3.46.1), а на существующей базе pragma без
  `VACUUM` ничего не меняет — её мигрирует первая чистка.
- `tests/test_quota.py` (6 тестов) и `tests/test_cleanup.py` (19) плюс
  мутационный гейт `tests/mutation_gate_m2.py`: 16 мутантов (без `BEGIN
  IMMEDIATE`, processing вне квоты, `>=` → `>`, 0 вместо «без лимита», purge без
  фильтра статуса, `<` → `<=` у обоих сроков, без `LIMIT` в батче удаления и
  обнуления, `incremental_vacuum` не до конца, pragma после WAL, без
  `wal_checkpoint`, проброс исключения чистки, inline вместо `to_thread`, цикл
  без `maybe_cleanup`) — все 16 убиты своими тестами на своих ассертах.
- `tests/test_m2_gaps.py` — 28 тестов: десять выживших мутантов независимого
  прогона M2 (Q06, C07–C10, W03–W07) и дефекты F1/B1/V1/L1 этой вехи. Сценарии
  `init_db()` идут в подпроцессах со своим `ANTICAPTCHA_DATABASE_PATH`, потому
  что `app.database` собирает engine при импорте, а дочерний процесс сначала
  готовит базу и печатает READY — замок берётся только после этого, иначе
  измерялся бы старт интерпретатора, а не ожидание блокировки.

### Fixed
- qwen CLI запускается в отдельной сессии (`start_new_session=True`), а при
  таймауте и отмене `_reap()` убивает всю группу процессов (`killpg`) и ждёт
  завершения не дольше `_REAP_TIMEOUT` (5 с). Раньше `await process.wait()`
  после `kill()` мог висеть бесконечно: в Python 3.11 он ждёт и закрытия pipe'ов,
  а их держат потомки node-процесса.
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
- В образе были ДВЕ дистрибуции OpenCV вместо одной. `pip list` показывал
  `opencv-python 5.0.0.93` (её тянет ultralytics: `opencv-python!=4.13.0.90,>=4.7.0`)
  и `opencv-python-headless 4.14.0.94` (её тянет easyocr), обе пишут в один
  `cv2/`, и импортировался не тот пакет, который запинен в `requirements.txt`:
  `cv2.__version__` был `5.0.0`. Теперь Dockerfile после установки зависимостей
  удаляет `opencv-python` и переустанавливает headless
  (`--force-reinstall --no-deps`, версия берётся grep'ом из `requirements.txt`,
  пин поднят до `5.0.0.93` — то, что фактически грузилось, и последний релиз).
  Удаление без переустановки ломает `cv2/` (файлы общие), поэтому reinstall
  обязателен. `pip check` теперь пишет «ultralytics requires opencv-python,
  which is not installed» — ожидаемо: ultralytics нужен импортируемый `cv2`,
  headless-сборка его даёт (проверено: YOLO `predict` и `easyocr.readtext`
  работают, ultralytics при predict ничего не доустанавливает).
- `task_id` больше не возвращается в оборот после чистки. Таблица `tasks`
  создаётся с `__table_args__ = {"sqlite_autoincrement": True}`: SQLite хранит
  максимум когда-либо выданного id в `sqlite_sequence` и выдаёт следующий за ним,
  поэтому purge, удаливший самую свежую строку, не отдаёт её id новой задаче, и
  клиент с сохранённым старым id получает 404 вместо своей новой задачи. Один
  `Column(..., autoincrement=True)` AUTOINCREMENT в SQLite не даёт (замерено на
  SQLAlchemy 2.0.23) — нужен именно табличный параметр. Существующая база 1.0.x
  мигрирует в `init_db()`: `ALTER TABLE` AUTOINCREMENT не добавляет, поэтому
  `_migrate_tasks_autoincrement()` в `app/database.py` пересоздаёт таблицу —
  переименовывает старую, снимает уехавшие вместе с ней индексы (иначе
  `ix_tasks_id` занято), создаёт таблицу из модели, переливает строки (это же
  заполняет `sqlite_sequence` максимумом id) и удаляет временную. Список колонок
  берётся из `Task.__table__.columns`, не хардкодом. Если таблицы нет или в её
  DDL уже есть AUTOINCREMENT, функция возвращает `False` и ничего не делает,
  поэтому повторный `init_db()` безопасен.
- `init_db()` больше не падает, когда API и воркер стартуют одновременно на
  свежем томе: создание таблиц и миграция `tasks` идут в одной транзакции
  `BEGIN IMMEDIATE` на одном соединении. Без замка пишущего `create_all` второго
  процесса умирал на `table users already exists` (воспроизведено); теперь он
  ждёт освобождения замка (`busy_timeout` 5 с) и видит уже закоммиченные таблицы.
- `init_db()` дожидается чужой блокировки, а не сдаётся после одной попытки.
  `busy_timeout` ограничивает одну попытку, а миграция во втором процессе может
  идти дольше — проигравший умирал на `database is locked` (замерено в образе:
  `sqlalchemy.exc.OperationalError … database is locked [SQL: BEGIN IMMEDIATE]`
  через 5,01 с), и старт API или воркера прерывался. Тело вынесено в
  `_init_db_once()` без изменений, обёртка `init_db(lock_wait_seconds=60.0)`
  повторяет его каждые 0,5 с, пока в тексте ошибки есть `locked` и не исчерпан
  бюджет; любая другая `OperationalError` (битый файл, том только на чтение)
  пробрасывается сразу.
- `purge_tasks()` отвергает `batch_size < 1` с `ValueError`: `LIMIT 0` в SQLite
  означает «ни одной строки», поэтому чистка молча ничего не делала и рапортовала
  порядок, а `LIMIT -1` снимает ограничение вовсе и возвращает весь бэклог в одну
  долгую транзакцию — ровно то, от чего батчи должны уходить.
- Разовая миграция `auto_vacuum` больше не запускается, когда на томе нет места
  на вторую копию базы: `_has_room_for_vacuum()` в `workers/cleanup.py` сверяет
  `shutil.disk_usage(<каталог базы>).free` с `2 * <размер файла базы>` и при
  нехватке пропускает `VACUUM` с предупреждением, а следующий цикл пробует снова.
  Раньше `VACUUM` падал на середине и повторялся каждый цикл, каждый раз держа
  блокировку записи всё время перестройки. `wal_checkpoint(TRUNCATE)` выполняется
  во всех трёх ветках. Пустой путь и `:memory:` проверку проходят без чтения ФС.
- Числовые настройки ограничены снизу (`Field(..., ge=...)` в `app/config.py`):
  `max_active_tasks_per_key >= 0`, `cleanup_interval_seconds >= 1`,
  `input_retention_hours >= 0`, `task_retention_days >= 0`. Отрицательная квота
  молча отключала лимит (`create_task` проверяет `if limit > 0`), отрицательный
  срок хранения сдвигал границу чистки `now - retention` в будущее и удалял
  свежие задачи, нулевой интервал запускал чистку на каждом опросе. Границы
  включительные: `max_active_tasks_per_key=0` по-прежнему значит «без лимита».

### Known limitations
- Остановка qwen CLI (`_reap`): `killpg` выполняется, только пока лидер не
  собран. Если CLI завершился раньше потомка, который держит его stdout/stderr,
  этот потомок не убивается. Воркер его не ждёт: ожидание ограничено
  `_REAP_TIMEOUT`, зависания нет, но процесс остаётся жить.

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