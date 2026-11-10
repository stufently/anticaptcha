# M2 — Playwright 1.65, один OpenCV, квоты на ключ, чистка задач

## 1. Шапка

- Репозиторий: `anticaptcha` (публичный). Дата спеки: 2026-11-10.
- BASE_SHA: `f79547394d01662bc8648dc6e4694d90ac823822` «CI: mount chart and config for
  image tests» (main после вех M1 и M1b; от `4083b1f` отличается только
  `.github/workflows/images.yml`, код и образ те же). Первичная разведка — на `5b2aa40`
  «Release 1.0.1»; ссылки на код и зонды пересверены на BASE (раздел 4).
- Исполнитель: `auto` (новая спека). Мутации по коду вехи гоняет ПРОТИВОПОЛОЖНЫЙ
  исполнитель. Исправления внутри вехи — тому же исполнителю.

## 2. Где работать

- Только одноразовый клон от BASE, созданный `make_clone.sh`; новая ветка
  `m2-playwright-quotas`. Живое дерево постановщика не трогать.
- git pull в клоне не делать; push в origin запрещён, работу заберёт постановщик через `git fetch` из клона.
- Docker — под своим uid (`--user "$(id -u):$(id -g)"` там, где контейнер пишет в
  bind-mount). На хост ничего не ставить.

Что кладёт постановщик ДО запуска (untracked, в `probes/` корня клона):

| Файл | sha256 | байт |
|---|---|---|
| `probes/m2_image_probe.py` | `0f994dabddd4e051516ec2b54803ec0e0a01e9f20879796c55cac44a85b4a246` | 2819 |
| `probes/m2_browser_probe.py` | `a7e5a17a5c3f16964ad782ae619e0410cdd160cb32d2c1d3ec548c560a5c8c87` | 3009 |
| `probes/m2_quota_cleanup_probe.py` | `2eb69d0b17d8f963411586d0a21bf2cd097fdf3ce0015086ca9f62663b51559c` | 16322 |
| `probes/m2_live_regression.py` | `83633eb2184e682947e37d19af42c204e433ee352cc5c88efb3dc61baeb8280c` | 3624 |
| `probes/m2_header_probe.py` | `b3990d3f1fa7f58923dec66b729a78da47296f11573f49171fe3570634aa5f5e` | 2756 |

Пробники — контракт вехи, читать их можно и нужно; править, коммитить и
удалять нельзя. Образ `anticaptcha:m2-base`, собранный из BASE
(`git archive f79547394d01662bc8648dc6e4694d90ac823822 | docker build -t anticaptcha:m2-base -`),
тоже кладёт постановщик: он нужен для замера «до» в шаге 5.6.

## 3. Задача и почему

1. **Playwright 1.40.0 → 1.65.0.** Сейчас Chromium 120 (ноябрь 2023), а браузер
   идёт с `--no-sandbox`: эксплойт рендерера на странице клиента сразу даёт код
   в воркере. Песочницу в нашей среде включить нельзя (раздел 4), значит
   остаётся только свежий Chromium.
2. **Один OpenCV.** В образе две дистрибуции пишут в один `cv2/`; грузится
   не та, что запинена.
3. **Квота активных задач на API-ключ.** Сейчас любой ключ кладёт в очередь
   неограниченно задач.
4. **Чистка.** `input_data` (до 5 МБ base64) лежит в SQLite вечно; том маленький,
   внешний бэкап может копировать файл базы целиком. Без чистки база растёт
   бесконечно.
5. **Без `pip install` в рантайме.** ultralytics подменяет `PIL.Image.open` и при
   ЛЮБОЙ ошибке открытия пытается доставить `pi-heif` через pip (раздел 4). В
   воркере с сетью это установка чужого кода от uid 1000 во время работы.
   Выключается переменной окружения образа.

Что сломается и чинится здесь же: смена пина OpenCV меняет `pip check`
(ultralytics объявляет зависимость `opencv-python`, её больше не будет — это
ожидаемо, раздел 4); блокировка `BEGIN IMMEDIATE` в `create_task` не должна
ломать существующие тесты `tests/test_api.py`, где одна сессия на все запросы.

## 4. Что проверено вживую, а что предположение

Всё ниже — команды в Docker на этом хосте, 2026-11-10. Ссылки файл:строка и
зонды — на BASE `4083b1f`; замеры, помеченные `5b2aa40`, сделаны до M1 и
остаются в силе, потому что `requirements.txt`, `Dockerfile`, `app/database.py`,
`app/api/tasks.py` и аргументы запуска Chromium между `5b2aa40` и BASE не
менялись (`git diff 5b2aa40 4083b1f` по этим файлам пуст; в `browser.py` M1
обернула запуск в `asyncio.Lock`, список аргументов прежний).

**Реестры (не по памяти):**
- PyPI `playwright`: latest **1.65.0** (загружен 2026-11-09), requires_python
  `>=3.10`, зависимость `greenlet>=3.1.1,<4`; `pyee` больше не зависимость.
  Предыдущий — 1.64.1 (2026-10-22). Источник: `https://pypi.org/pypi/playwright/json`,
  GitHub releases `microsoft/playwright-python`. 1.65.0 несёт Chromium
  158.0.8127.18 (Chrome for Testing), 1.64.x — 156.
- PyPI `playwright-stealth`: latest **2.0.3** (2026-04-04), зависимость
  `playwright>=1.40.0` без верхней границы. Уже стоит, пин не меняется.
- PyPI `opencv-python-headless`: latest **5.0.0.93** (2026-07-02).

**Существующий код (файл:строка):**
- `requirements.txt:12` `playwright==1.40.0`, `:13` `playwright-stealth==2.0.3`,
  `:21` `opencv-python-headless==4.14.0.94`, `:22` `ultralytics==8.4.118`,
  `:20` `easyocr==1.7.1`.
- `Dockerfile:46` ставит `requirements.txt`, `:49` `qwen-code-sdk`, `:52`
  `ENV ULTRALYTICS_SAFE_LOAD=1`, `:56` `playwright install chromium` (качает
  Chromium и headless shell), `:92` uid 1000, `:99` `USER anticaptcha`. Тесты в
  образ не копируются, CI монтирует `tests/` (`.github/workflows/images.yml:89`,
  `--network none`). `chart/` и `config/` в образ тоже не попадают
  (`.dockerignore`, `config/` копируется только `settings.json`), а с M1/M1b три
  теста читают их из корня репо (`tests/test_version.py`,
  `tests/test_m1_gaps.py::test_C16_...`, `tests/test_vision_llm_sandbox.py::
  test_qwen_settings_disable_memory_agent`): без `-v chart`/`-v config` сьют
  даёт `3 failed, 165 passed` (CI на BASE упал ровно на этом; починено
  следующим коммитом main, только `images.yml`). Поэтому AC-005 их монтирует.
- `app/utils/browser.py:25-79` `get_browser` под `asyncio.Lock` (`:23`, `:27`,
  с M1): `:41-49` аргументы запуска, первый `--no-sandbox` (`:42`); `:52-56`
  stealth-аргументы; `:58-67` `launch` с остановкой драйвера при сбое; `:22`
  `Stealth()`; `:108` `await self._stealth.apply_stealth_async(page)` —
  единственный вызов stealth в `app/` и `workers/`. `new_context` (`:112-118`,
  UA `Chrome/120` строкой) и `app/utils/stealth.py::create_stealth_page` нигде
  не вызываются. Чем пользуются солверы: `page.goto`, `wait_for_selector`,
  `frame_locator(...).locator(...)`, `locator().click/count/all/first/text_content/
  bounding_box/screenshot/wait_for/get_attribute/fill`, `page.mouse.move/down/up`,
  `evaluate`, `set_extra_http_headers`, `add_init_script`, `browser.new_page/
  new_context`. Все эти атрибуты есть в 1.65.0 (проверено `hasattr` по классам
  `playwright.async_api`).
- Release notes 1.41–1.65, что может задеть солверы поведением (не API):
  1.64.0 — элементы внутри скрытого iframe считаются скрытыми; 1.65.0 — действия
  ждут, пока элемент перестанет быть `inert`, и Python-клиент переписан
  построчным портом Node-клиента («API не менялся»); 1.57 — сборки Chrome for
  Testing; 1.49 — `headless=True` у `chromium` = headless shell. Удалённые API
  (`page.accessibility`, `_react/_vue`, `devtools`, `handle` у `expose_binding`)
  в коде не используются. **Предположение:** поведенческие изменения на
  демо-капчах не всплывут — это и меряет шаг 5.6.
- `app/api/tasks.py:48-69` `create_task(task_data, auth_data, db)` без
  ограничений; `get_api_key_and_user` (`:15-45`) делает только SELECT и в
  FastAPI делит с эндпоинтом одну сессию `get_db` (`app/database.py:36-42`).
- `app/database.py:21-29` слушатель `connect`: `:27` `journal_mode=WAL`, `:28`
  `busy_timeout=5000`; `auto_vacuum` не задаётся. `:45-48` `init_db` = импорт
  `app.models` + `create_all`.
- `app/models/task.py:17` статусы `pending|processing|solved|failed`; `:20`
  `input_data` `nullable=False` (NULL записать нельзя, а миграций в проекте нет);
  `:24` `created_at` `server_default=func.now()` — в SQLite это UTC.
  `workers/task_worker.py:78,104` пишет `started_at`/`solved_at` через
  `datetime.utcnow()`; у failed-задачи `solved_at` пуст (`:111-114` — сбой
  решения, `:152-157` — `recover_interrupted_tasks`), поэтому возраст считается
  ТОЛЬКО по `created_at`.
- API не может создать задачу с `input_data == ""`: `tasks.py:61`
  `json.dumps(dict)` даёт минимум `{}`. Воркер разбирает `input_data` только у
  задачи, взятой из pending (`task_worker.py:88` в `process_task`, вызов —
  `:211-216`). Значит `""` — однозначный признак «вход вычищен».
- `app/api/tasks.py:88-95` GET отдаёт `status/result/error/created_at/solved_at`
  и `input_data` не читает.
- `workers/task_worker.py:174-236` `run()` после M1: `:180` `init_db()`
  (сбой фатален), `:185` `self._try_recover()` (флаг `_recovery_pending`,
  `:40`, `:162-172`), `:188` `setup_solvers`, `:194-199` фоновая задача
  `heartbeat_loop` в том же event loop (`workers/heartbeat.py`); `:200-236`
  `try/finally`, внутри `:201-226` цикл `while self.running:` — `:205-206`
  повтор восстановления, пока флаг взведён, `:208` сессия, `:211-213` выборка
  pending, `:215-219` задача или `sleep`; `finally` снимает heartbeat. Значит
  синхронная работа в потоке event loop (например, `VACUUM`) останавливает и
  heartbeat: liveness-проба чарта (`workers.heartbeat --check`) убьёт под.
  `app/models/stats.py` — таблица `stats`, чистка её не трогает.
- `app/config.py:7-53` `Settings(BaseSettings)`, `:53` `env_prefix =
  "ANTICAPTCHA_"`: поле `max_active_tasks_per_key` читается из
  `ANTICAPTCHA_MAX_ACTIVE_TASKS_PER_KEY`. M1 добавила `worker_heartbeat_*` и
  `max_image_*` (`:23-34`).
- Базовый прогон на BASE: `docker run --rm --network none -v "$PWD/tests:/app/tests:ro"
  -v "$PWD/chart:/app/chart:ro" -v "$PWD/config:/app/config:ro"
  anticaptcha:m2-base python -m pytest tests -q -p no:cacheprovider` →
  `168 passed` за 13,2 с.

**OpenCV в образе** (`docker build` из `git archive 5b2aa40`; на `m2-base` из
BASE `pip list` тот же — `opencv-python 5.0.0.93`, `opencv-python-headless
4.14.0.94`):
`pip list` — `opencv-python 5.0.0.93` И `opencv-python-headless 4.14.0.94`;
`cv2.__version__ == "5.0.0"`. `opencv-python` тянет **ultralytics**
(`opencv-python!=4.13.0.90,>=4.7.0`), headless — **easyocr** (без версии).
То есть в проде сейчас фактически работает cv2 5.0. Эксперимент: `pip uninstall -y
opencv-python` + `pip install --force-reinstall --no-deps
opencv-python-headless==5.0.0.93` → одна дистрибуция, `cv2` 5.0.0, YOLO
`predict` и `easyocr.Reader(...).readtext` работают, ultralytics при predict
ничего не доустанавливает; `pip check` пишет «ultralytics requires opencv-python,
which is not installed» — ожидаемо и допустимо. Uninstall без reinstall ломает
`cv2/` (файлы общие), поэтому reinstall обязателен.
**Решение постановщика:** пин headless **5.0.0.93** (то, что реально грузится
сейчас, и последний релиз), а не 4.14.0.94: откат на 4.x поменял бы рабочий cv2.

**Песочница Chromium 158** (образ `5b2aa40` + playwright 1.65.0, uid 1000,
дефолтный seccomp docker, без привилегий; аргументы запуска с тех пор те же):
- без `--no-sandbox` при текущем `--no-zygote` — «Zygote cannot be disabled if
  sandbox is enabled»;
- без `--no-sandbox/--no-zygote/--disable-setuid-sandbox` — `FATAL ... No usable
  sandbox!` (нужен unprivileged user namespace, его режет seccomp);
- с `--security-opt seccomp=unconfined` — взлетает. Это и есть причина;
- SUID `chrome_sandbox` (root, 4755, `CHROME_DEVEL_SANDBOX`) — «Zygote process
  exited prematurely with exit code 82»; с `no-new-privileges` — «not running as root».
- Playwright сам добавляет `--no-sandbox`, пока `chromium_sandbox=False`
  (умолчание), так что строка в `browser.py:42` лишь дублирует умолчание.
Вывод: в контейнере без `seccomp: Unconfined`/`CAP_SYS_ADMIN` песочница
невозможна; `--no-sandbox` остаётся, обоснование — комментарием в коде (5.1).

**Stealth на 1.65.0:** `Stealth().apply_stealth_async(page)` работает: на голой
странице UA содержит `HeadlessChrome/158...`, после stealth — `Chrome/158...`,
`window.chrome` есть, `navigator.languages` = `['en-US','en']`. На 1.40 то же самое
со 120.

**SQLite 3.46.1 в образе, замеры:**
- `PRAGMA auto_vacuum=INCREMENTAL` действует на НОВОЙ базе, только если выполнен
  ДО `PRAGMA journal_mode=WAL` (в обратном порядке получается `auto_vacuum=0`).
  На существующей базе pragma без `VACUUM` ничего не меняет.
- `PRAGMA auto_vacuum=INCREMENTAL; VACUUM;` в режиме WAL переводит базу в
  `auto_vacuum=2`, режим остаётся `wal`.
- **Грабли:** в Python (`sqlite3`, Python 3.11, и через SQLAlchemy
  `exec_driver_sql`) `execute("PRAGMA incremental_vacuum")` освобождает ОДНУ
  страницу за вызов (freelist 12800 → 12799, с `.fetchall()` и без).
  `dbapi_conn.executescript("PRAGMA incremental_vacuum;")` доводит до freelist 0.
- `VACUUM` базы с 1 ГБ ЖИВЫХ данных: 4,8 с на NVMe этого хоста; при этом `-wal`
  вырос до 1083 МБ до `wal_checkpoint(TRUNCATE)`. Нужно свободное место ≈ размер
  живых данных. После чистки (живого почти нет) `VACUUM` того же файла — 0,00 с,
  а checkpoint — 0,12 с, файл сжался до долей МБ. Обнуление `input_data` у 4096
  строк по 256 КБ батчами по 100 — 4,5 с, `-wal` 26 МБ. **Предположение:** на
  сетевом томе всё медленнее в 10–50 раз; поэтому `VACUUM` идёт ТОЛЬКО после
  чистки, когда живых данных мало.
- Гонка квоты (SQLAlchemy 2.0.23, pysqlite, 5 потоков, лимит 1, сон 0,3 с после
  `COUNT`): проверка и вставка без блокировки — 5 строк; с
  `db.connection().exec_driver_sql("BEGIN IMMEDIATE")` перед `COUNT` — ровно 1
  строка, остальные 429. Предшествующие SELECT в той же сессии не мешают.

**Ultralytics и `PIL.Image.open` (образ `m2-base`, BASE):**
- `import ultralytics` подменяет `PIL.Image.open` на
  `ultralytics.utils.patches.image_open` (`PIL.Image.open.__module__ ==
  "ultralytics.utils.patches"`); исходный опенер лежит в
  `ultralytics.utils.patches._image_open`. Подмена при ЛЮБОМ исключении открытия
  зовёт `check_requirements("pi-heif")`, затем `from pi_heif import ...`.
- `pi_heif` в образе нет (`ModuleNotFoundError`). С `--network none`
  ultralytics пишет «requirement ['pi-heif'] not found, attempting AutoUpdate...
  AutoUpdate skipped (offline)». С сетью он запустит pip от uid 1000 (HOME
  писуч — поставит в `~/.local`). Переключатель — `AUTOINSTALL =
  env_bool("YOLO_AUTOINSTALL", True)` (`ultralytics/utils/__init__.py:70`,
  проверка `checks.py:625`); с `YOLO_AUTOINSTALL=false` попытки установки нет,
  ошибка та же `ModuleNotFoundError`. Установка `pi-heif` в образ — НЕ решение:
  HEIF клиенту не нужен (`ALLOWED_IMAGE_FORMATS` — PNG/JPEG/WEBP/BMP).
- `workers/solvers/image_text.py:19-39` `_open_header` (M1) обходит подмену: если
  `Image.open` не из `PIL.Image`, берёт `_image_open` из модуля подмены. Без
  обхода PNG-заголовок 20000×20000 и мусор оба дают «Unsupported or corrupt
  image: ModuleNotFoundError: No module named 'pi_heif'», то есть бомба
  перестаёт отличаться от битого файла. Тестов на это в `tests/` нет: ни один
  тест не импортирует ultralytics. Обход держится на приватном имени
  `_image_open` пина `ultralytics==8.4.118` — пин в этой вехе не меняется, а
  проверку несёт `probes/m2_header_probe.py` (AC-002).

**Живой прогон демо на `5b2aa40` (до) и на эталоне с 1.65.0 (после)**, скрипт
`probes/m2_live_regression.py`: ВСЕ три случая — `error` на ОБЕИХ версиях.
reCAPTCHA v2 — «Could not solve image challenge» (11 с / 22 с; checkbox кликается,
картинку без Vision LLM не решить); hCaptcha — таймаут `wait_for_selector`
iframe 30 с; Turnstile — таймаут iframe 60 с. Классы ошибок до и после
совпадают. Значит регресс «было решено — стало нет» на демо сейчас не виден в
принципе; шаг 5.6 сравнивает классы ошибок и ловит только новые (запуск
браузера, падение страницы, исключения Playwright другого типа). Починка
солверов — отдельная задача, не эта веха.

**Зонды пробников на BASE `4083b1f`** (образ `anticaptcha:m2-base`, `--network
none`; пробники после M1 не менялись, их интерфейсы — `BrowserManager().
get_browser()/new_page(stealth=)/close()`, `HAS_STEALTH`, `TaskWorker()` без
аргументов, `while` внутри `TaskWorker.run` — в BASE на месте):
- `m2_image_probe.py` — `rc=1`, 5 провалов: pins/installed `playwright` 1.40.0,
  pins/installed `opencv-python-headless` 4.14.0.94, «OpenCV distributions in
  image: ['opencv-python', 'opencv-python-headless']».
- `m2_browser_probe.py` — `rc=1`, единственный провал «Chromium 120.0.6099.28,
  expected major 158» (запуск, страница и stealth на 1.40 работают).
- `m2_quota_cleanup_probe.py` — `12 failed`: `AttributeError` у `settings`
  (`max_active_tasks_per_key`), `auto_vacuum` `0 == 2`, `ModuleNotFoundError:
  No module named 'workers.cleanup'`, нет `run_cleanup` в `workers.task_worker`,
  «TaskWorker.run must `await self.maybe_cleanup()` inside its main while-loop».
- `m2_header_probe.py` — `rc=1`, единственный провал «ultralytics
  AUTOINSTALL=True, expected False»; проверки обхода подмены зелёные. С `-e
  YOLO_AUTOINSTALL=false` — «header probe: OK». Мутант `_open_header` →
  `Image.open(...)` (без обхода) даёт 2 провала с `pi_heif`.
- Эталон, перенесённый на BASE (конфиг, квота, pragma, `workers/cleanup.py`,
  `maybe_cleanup` в цикле после повтора восстановления и до сессии): квотный
  пробник `12 passed`, полный сьют `168 passed`.
- Ранее на `5b2aa40`: десять уклончивых реализаций (без `BEGIN IMMEDIATE`,
  pragma после WAL, `execute` вместо `executescript`, чистка в потоке event loop,
  без `LIMIT` в батче, без фильтра статуса, без checkpoint, processing не
  считается, цикл не зовёт чистку) пробник ловил все; выжил один эквивалентный —
  лишний `incremental_vacuum` сразу после `VACUUM`. Квотный пробник после M1 не
  менялся, части воркера, которые он проверяет, тоже.

## 5. Что сделать

**5.1 Playwright** — `requirements.txt`: `playwright==1.65.0`; stealth остаётся
2.0.3. `Dockerfile` не менять, кроме 5.2. `app/utils/browser.py`: ТОЛЬКО
комментарий над списком `args = [` в `get_browser` (`:41`, внутри блока под
`self._lock`) — почему `--no-sandbox` (seccomp режет user namespace,
setuid-sandbox не работает без root; ссылка на `docs/specs/limits.md`), строки
кода не трогать, включая блокировку и обработку сбоя запуска из M1. Солверы не править: если живой прогон (5.6) показал регресс из-за
обновления — стоп и доклад (раздел 9).

**5.2 OpenCV** — `requirements.txt`: `opencv-python-headless==5.0.0.93`.
`Dockerfile`: сразу после `RUN pip install ... qwen-code-sdk` отдельный `RUN`:
`pip uninstall -y opencv-python` и `pip install --no-cache-dir --force-reinstall
--no-deps` той строки `opencv-python-headless==…`, что стоит в `requirements.txt`
(взять grep'ом, версию вторым местом не писать). Комментарий: кто тянет
`opencv-python` и почему `pip check` про ultralytics — ожидаем.
В том же `Dockerfile` рядом с `ENV ULTRALYTICS_SAFE_LOAD=1` (`:52`) — `ENV
YOLO_AUTOINSTALL=false` с комментарием: ultralytics при любой ошибке
`PIL.Image.open` пытается ставить `pi-heif` через pip в рантайме. `pi-heif` в
образ НЕ ставить. Пин `ultralytics==8.4.118` (и `torch`, `torchvision`,
`easyocr`, Pillow) не менять: обход подмены в `_open_header`
(`workers/solvers/image_text.py:19-39`) держится на
`ultralytics.utils.patches._image_open` этого пина; проверка — пробник
`m2_header_probe.py` в AC-002.

**5.3 Настройки** — `app/config.py`, поля `Settings`:
`max_active_tasks_per_key: int = 20` (0 = без лимита),
`cleanup_interval_seconds: int = 600`, `input_retention_hours: float = 1`,
`task_retention_days: float = 7`. Читать из `settings` в момент использования,
не копировать в модульные константы (пробник меняет их `monkeypatch`'ем).

**5.4 Квота** — `app/api/tasks.py::create_task`, сигнатура прежняя. Если
`settings.max_active_tasks_per_key > 0`: `BEGIN IMMEDIATE` на соединении сессии
(`db.connection().exec_driver_sql("BEGIN IMMEDIATE")`), затем ОДИН SQL
`COUNT(...)` (через `func.count`, не загрузкой строк) задач этого `api_key_id` со
статусом `pending` или `processing`; если `>= limit` — `db.rollback()` и
`HTTPException(429, detail=f"Too many active tasks for this API key: limit is {limit}")`;
иначе вставка и `commit` в той же транзакции. Существующие тесты с общей сессией
не править: если `BEGIN IMMEDIATE` падает «cannot start a transaction within a
transaction», чинить код, а не тесты.

**5.5 Чистка** — новый `workers/cleanup.py`, все функции топ-уровня:
- `purge_tasks(engine, now=None, input_retention_hours=None,
  task_retention_days=None, batch_size=100) -> dict` →
  `{"inputs_cleared": int, "tasks_deleted": int}`. `now` — наивный UTC,
  умолчание `datetime.utcnow()`; `None` у сроков — взять из `settings`. Только
  через SQLAlchemy (Connection/Session, не raw dbapi), каждый батч ≤ `batch_size`
  строк и свой `commit`. Порядок: СНАЧАЛА удалить задачи со статусом
  `solved|failed` и `created_at < now - task_retention_days`; ПОТОМ у
  `solved|failed` с `created_at < now - input_retention_hours` и
  `input_data <> ''` записать `input_data = ''`. Сравнение строгое (`<`).
  `pending`/`processing` не трогать никогда; `result`, `error_message` и таблицу
  `stats` не трогать. `inputs_cleared` — число строк, где `input_data` стал `''`.
- `reclaim_space(engine) -> None`: если `PRAGMA auto_vacuum != 2` —
  `PRAGMA auto_vacuum=INCREMENTAL` и `VACUUM` (разовая миграция старой базы);
  иначе `incremental_vacuum` ДО КОНЦА (freelist 0; см. грабли в разделе 4); в
  конце `PRAGMA wal_checkpoint(TRUNCATE)`. Полный `VACUUM` на базе с
  `auto_vacuum=2` не запускать.
- `run_cleanup(engine=None) -> dict`: `purge_tasks`, затем `reclaim_space`
  (именно в этом порядке: миграционный VACUUM должен идти по уже вычищенной
  базе); `engine` по умолчанию — `app.database.engine`.
- `app/database.py`: в слушателе `connect` добавить
  `PRAGMA auto_vacuum=INCREMENTAL` ПЕРЕД `journal_mode=WAL`.
- `workers/task_worker.py`: `import time`, `from workers.cleanup import run_cleanup`;
  метод `async def maybe_cleanup(self, now: Optional[float] = None) -> bool`
  (`now` по умолчанию `time.monotonic()`): первый вызов запускает чистку сразу,
  дальше — если с прошлого запуска прошло `>= settings.cleanup_interval_seconds`;
  запуск — `await asyncio.to_thread(run_cleanup)`; исключение логировать и не
  пробрасывать; запуск со сбоем тоже считается запуском (интервал отсчитывается
  от него). Возвращает `True`, если `run_cleanup` вызывалась. В цикле
  `while self.running:` в `run()` (`task_worker.py:201`) — `await
  self.maybe_cleanup()` на каждой итерации, ПОСЛЕ блока `if
  self._recovery_pending: self._try_recover()` (`:205-206`) и ДО `db =
  SessionLocal()` (`:208`). Так первая чистка идёт после восстановления
  прерванных задач и при уже запущенном heartbeat; `asyncio.to_thread`
  обязателен ещё и потому, что миграционный `VACUUM` в потоке event loop
  остановил бы heartbeat (раздел 4) и liveness-проба убила бы под посреди
  `VACUUM`. Остальное в воркере (`init_db()`, `_try_recover`/`_recovery_pending`,
  heartbeat-задача и её снятие в `finally`, `process_task`) не менять.

**5.6 Живой регресс (отчётный шаг, не гейт)** — с сетью:
`docker run --rm -v "$PWD/probes:/app/probes:ro" anticaptcha:m2-base python probes/m2_live_regression.py before`
и то же с `anticaptcha:m2-accept` и меткой `after` (плюс `-v` на `app/` и
`workers/` клона). Склеить в `m2-live-regression.json` в корне клона:
`{"before": <вывод>, "after": <вывод>}`; файл не коммитить. Демо: reCAPTCHA v2
`https://www.google.com/recaptcha/api2/demo`, hCaptcha
`https://accounts.hcaptcha.com/demo`, Turnstile `https://demo.turnstile.workers.dev/`
(тестовый ключ `1x00000000000000000000AA`; **предположение:** страница
Cloudflare). Исходы сравнить в `note` критерия AC-007: регресс — случай, который
`before` решил, а `after` нет, ИЛИ ошибка `after` другого класса, чем `before`
(например, браузер не запустился вместо таймаута ожидания iframe). Числа про качество
решения писать ТОЛЬКО из этого файла; от себя — запрещено.

**5.7 Тесты и мутации** — новые `tests/test_quota.py` (лимит, 429 и текст,
другой ключ, processing считается, solved/failed освобождают, 0 = без лимита,
гонка) и `tests/test_cleanup.py` (правила purge, граница ровно в срок, батчи,
`stats` цел, миграция и incremental, GET после обнуления, `maybe_cleanup`).
`tests/mutation_gate_m2.py` — обвязка по шаблону (исходные байты и sha256 →
целевой тест зелёный на чистом дереве → фрагмент ровно один раз → мутация →
прогон ИМЕННО целевого теста → откат в `finally` и сверка sha256 → «убит» только
если упал свой тест на своём ассерте). Мутации минимум: без `BEGIN IMMEDIATE`;
processing не считается; `>=` → `>` в лимите; 0 перестаёт значить «без лимита»;
purge без фильтра статуса; `<` → `<=` у срока; без `LIMIT`/батча; incremental
не до конца; pragma `auto_vacuum` после WAL; без `wal_checkpoint`; исключение
чистки пробрасывается; без проверки интервала. Печатает «убит/выжил» и первую
упавшую строку; 0 — все убиты. Обвязка запускается из-под uid постановщика (не 1000):
`/app/data` образа ему не писуч, поэтому база тестов — по `ANTICAPTCHA_DATABASE_PATH`
в `/tmp` (см. команду AC-006); сам гейт запускает pytest как подпроцесс. Эквивалентный мутант исключать только с
письменным обоснованием в самом файле.

**5.8 Учёт** — `CHANGELOG.md` (новая версия не нужна, раздел Unreleased) и
`docs/specs/limits.md` (квота, сроки хранения, почему `--no-sandbox`). Этот файл
(`docs/specs/m2-playwright-quotas.md`) закоммитить вместе с работой.

## 6. Не трогать

`workers/solvers/**` (в т.ч. `url_guard.py` и `image_text.py` с `_open_header`)
и `workers/classifiers/**`, `workers/heartbeat.py`, строки кода
`app/utils/browser.py` (разрешён только комментарий, 5.1), `chart/`, `config/`,
`.github/`, `Dockerfile.minimal`, `requirements-minimal.txt`, `app/main.py`,
`app/__init__.py`, в `requirements.txt` — все пины, кроме `playwright` и
`opencv-python-headless`; существующие файлы в `tests/`, `probes/`.
Исключение — эта спека: её коммитить.

## 7. Критерии приёмки

Команды запускаются из корня клона в указанном порядке: AC-001 собирает образ,
остальные им пользуются.

- **AC-001** — образ собирается из клона.
  `bash -c 'docker build -q -t anticaptcha:m2-accept . >/dev/null'`

- **AC-002** — в образе один OpenCV нужной версии, пины Playwright/stealth, Chromium на месте; авто-установка ultralytics выключена, проверка заголовка картинки по-прежнему обходит подмену `PIL.Image.open`.
  `bash -c 'echo "0f994dabddd4e051516ec2b54803ec0e0a01e9f20879796c55cac44a85b4a246  probes/m2_image_probe.py" | sha256sum -c - && echo "b3990d3f1fa7f58923dec66b729a78da47296f11573f49171fe3570634aa5f5e  probes/m2_header_probe.py" | sha256sum -c - && docker run --rm --network none -v "$PWD/probes:/app/probes:ro" anticaptcha:m2-accept python probes/m2_image_probe.py && docker run --rm --network none -v "$PWD/probes:/app/probes:ro" anticaptcha:m2-accept python probes/m2_header_probe.py'`

- **AC-003** — Chromium 158 запускается теми же аргументами, открывает локальную страницу, stealth применяется.
  `bash -c 'echo "a7e5a17a5c3f16964ad782ae619e0410cdd160cb32d2c1d3ec548c560a5c8c87  probes/m2_browser_probe.py" | sha256sum -c - && docker run --rm --network none -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/probes:/app/probes:ro" anticaptcha:m2-accept python probes/m2_browser_probe.py'`

- **AC-004** — квота, гонка, правила чистки, батчи, миграция и incremental, GET после обнуления, интеграция в воркер.
  `bash -c 'echo "2eb69d0b17d8f963411586d0a21bf2cd097fdf3ce0015086ca9f62663b51559c  probes/m2_quota_cleanup_probe.py" | sha256sum -c - && docker run --rm --network none -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/probes:/app/probes:ro" anticaptcha:m2-accept python -m pytest probes/m2_quota_cleanup_probe.py -q -p no:cacheprovider'`

- **AC-005** — весь сьют проекта (старые и новые тесты) зелёный на коде клона.
  `bash -c 'docker run --rm --network none -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/tests:/app/tests:ro" -v "$PWD/chart:/app/chart:ro" -v "$PWD/config:/app/config:ro" anticaptcha:m2-accept python -m pytest tests -q -p no:cacheprovider'`

- **AC-006** — каждая мутация из 5.7 убита своим тестом.
  `bash -c 'docker run --rm --network none --user "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp -e ANTICAPTCHA_DATABASE_PATH=/tmp/m2gate/anticaptcha.db -v "$PWD/app:/app/app" -v "$PWD/workers:/app/workers" -v "$PWD/tests:/app/tests" anticaptcha:m2-accept python tests/mutation_gate_m2.py'`

- **AC-007** — живой регресс до/после записан (форма и версии; исходы — в note).
  `bash -c 'echo "83633eb2184e682947e37d19af42c204e433ee352cc5c88efb3dc61baeb8280c  probes/m2_live_regression.py" | sha256sum -c - && python3 probes/m2_live_regression.py --check m2-live-regression.json'`

- **AC-008** — изменены только разрешённые файлы; в browser.py добавлены только комментарии.
  `bash -c 'test -z "$(git diff --name-only f79547394d01662bc8648dc6e4694d90ac823822...HEAD | grep -v -E "^(requirements[.]txt|Dockerfile|app/config[.]py|app/database[.]py|app/api/tasks[.]py|app/utils/browser[.]py|workers/cleanup[.]py|workers/task_worker[.]py|tests/test_quota[.]py|tests/test_cleanup[.]py|tests/mutation_gate_m2[.]py|CHANGELOG[.]md|docs/specs/limits[.]md|docs/specs/m2-playwright-quotas[.]md)\$")" && test -z "$(git diff -U0 f79547394d01662bc8648dc6e4694d90ac823822...HEAD -- app/utils/browser.py | grep -E "^[-+]" | grep -v -E "^([+][+][+]|---|[+][[:space:]]*#)")"'`

- **AC-009** — обязательные файлы вехи есть в диффе.
  `bash -c 'for f in requirements.txt Dockerfile workers/cleanup.py tests/test_quota.py tests/test_cleanup.py tests/mutation_gate_m2.py CHANGELOG.md docs/specs/m2-playwright-quotas.md; do git diff --name-only f79547394d01662bc8648dc6e4694d90ac823822...HEAD | grep -qx "$f" || exit 1; done'`

- **AC-010** — дерево чистое.
  `bash -c 'test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)probes" ":(exclude)m2-live-regression.json")"'`

## 8. Авторевью и контракт отчёта

Политика `cross-review-v1` (полный текст — шаблон `spec-template.md`, раздел
«Автономное перекрёстное ревью»). Коротко: коммит → REVIEW_SHA; оба ревьюера
параллельно на `f79547394d01662bc8648dc6e4694d90ac823822..REVIEW_SHA`; пара по backend исполнителя
(Codex/Spark → `agy` + `qwen`; Qwen → `codex` + `agy`); один заход исправлений →
FINAL_SHA; одна проверка `REVIEW_SHA..FINAL_SHA`. Квитанции пишет только
обёртка, путь абсолютный:

`bash $HOME/.claude/skills/executor-milestone/scripts/review_run.sh initial <ревьюер> --clone <клон> --base f79547394d01662bc8648dc6e4694d90ac823822 --range f79547394d01662bc8648dc6e4694d90ac823822..<REVIEW_SHA> --exclude docs/specs/m2-playwright-quotas.md --context "M2 playwright/opencv/quota/cleanup; только чтение"`

Спека постановщика коммитится дословно и в диапазон ревью не входит (вход ревьюера
ограничен 100 000 Б; на M1 спека заняла почти половину лимита). Ревьюеры читают спеку
из снимка на REVIEW_SHA. Пробники `probes/` не коммитятся и в дифф не попадают.
Исключение — только одно:

REVIEW_EXCLUDE: docs/specs/m2-playwright-quotas.md

Контекст ревьюерам: публичный репозиторий; гонка квоты; не блокирует ли чистка
воркер; миграция старой базы; не ушёл ли дифф за раздел 6.

### Контракт отчёта

`report.json` в КОРНЕ клона, untracked. Записей в `criteria` ровно 10:
AC-001…AC-010. `blocked` — штатный исход, когда среда не даёт выполнить критерий:
`"rc": null` и дословная ошибка в `note`. Обходить несовместимость запрещено.

```json
{
  "schema_version": 2,
  "policy_id": "cross-review-v1",
  "spec_sha256": "<sha256 файла docs/specs/m2-playwright-quotas.md>",
  "base_sha": "f79547394d01662bc8648dc6e4694d90ac823822",
  "reviewed_sha": "<коммит, отданный на ревью>",
  "final_sha": "<HEAD после единственного захода фиксов>",
  "executor": {"backend": "qwen|spark|codex", "model": "<точная модель>"},
  "review": {
    "initial_receipts": ["<квитанция 1>", "<квитанция 2>"],
    "verification_receipts": [],
    "resolutions": []
  },
  "handoff_status": "ready",
  "criteria": [
    {"id": "AC-001", "status": "pass|fail|blocked",
     "command": "<команда ИЗ ЭТОЙ СПЕКИ, посимвольно>", "rc": 0, "note": "…"}
  ]
}
```

После сборки — `python3 $HOME/.claude/skills/executor-milestone/scripts/accept_run.py <клон> --spec docs/specs/m2-playwright-quotas.md --dry-run`, добиться кода 2.

## 9. Контракт на невыполнимое

Остановись, запиши `report-blocked.md` и доложи, НЕ обходя:
- Playwright 1.65.0 не ставится/не запускается в образе, или живой прогон 5.6
  даёт регресс в смысле 5.6 — правка солверов вне этой вехи;
- для работы нужен файл из раздела 6 или правка пробника;
- `BEGIN IMMEDIATE` несовместим с существующими тестами без их правки;
- `m2_header_probe.py` падает на обходе подмены (а не на `AUTOINSTALL`) —
  значит, сменился ultralytics или Pillow; `image_text.py` вне вехи;
- миграция `auto_vacuum` невозможна без полного VACUUM живой базы до чистки.
Подмена окружения и глушители кода возврата в командах запрещены.

## 10. Стыки

Следующей вехе: квота и сроки хранения — настройки окружения с префиксом
`ANTICAPTCHA_`; база новых установок создаётся с `auto_vacuum=INCREMENTAL`,
старые мигрируют при первой чистке; `--no-sandbox` остаётся, пока среда
запуска не даст unprivileged user namespaces (seccomp). Значения в чарте не
выставлены — работают умолчания кода. Апгрейд ultralytics — только вместе с
пересмотром `_open_header` (приватное `_image_open`). Мёртвый код с UA
`Chrome/120` строкой (`BrowserManager.new_context`,
`app/utils/stealth.py::create_stealth_page`) — убрать или обновить отдельно.
