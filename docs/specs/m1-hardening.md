# Веха M1 «hardening»: бомба-картинка, старт воркера, мёртвый Chromium, liveness, песочница vision LLM, секреты воркера

- Репозиторий `anticaptcha` (публичный GitHub `stufently/anticaptcha`, ветка `main`), дата постановки 10.11.2026.
- BASE_SHA: `5b2aa40281af612cd6d4edbcf4d850b3392436bb` («Release 1.0.1»). Это HEAD, с которого снят клон, левая
  граница диффа для ревью и значение `base_sha` в отчёте.
- Исполнитель: `auto` (Qwen или Spark, выбирает лаунчер). Мутации по новым тестам после приёмки гоняет
  противоположный исполнитель, в скоуп вехи это не входит.
- Критериев: 9. run_id: `<basename клона>-5b2aa40281af` (формула `review_run.sh`).
- ⚠️ Репозиторий публичный: в коммиты, тесты, комментарии и CHANGELOG не писать ничего об инфраструктуре
  владельца (домены, имя кластера, namespace, хранилище секретов, IP, пути домашних каталогов хоста).
  Нейтрально: «k8s-кластер», «том RWO», «внешний Secret».

## Где работать

- Одноразовый клон, выданный постановщиком (путь — в указателе запуска), новая ветка `m1-hardening` от BASE.
  Живое дерево репозитория не трогать.
- git pull в клоне не делать; push в origin запрещён, работу заберёт постановщик через `git fetch` из клона.
  `git add` — по именам, не `-A`.
- Всё — в Docker под своим пользователем, на хост ничего не ставить. Образ проекта собирается тегом
  `anticaptcha:m1` (`docker build -t anticaptcha:m1 .`; слои зависимостей в кэше хоста, пересборка после правки
  кода — только `COPY app/ workers/` и `chown`). `docker system prune` и удаление чужих образов запрещены.
- Тесты гоняются в образе, исходники и тесты монтируются read-only:
  `docker run --rm --network none -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m1 python -m pytest -q -p no:cacheprovider <узлы>`.
  Весь `/app` монтировать нельзя: в образе там модели EasyOCR и YOLO.

### Что кладёт постановщик до запуска

| Файл | sha256 | Размер | Статус |
| --- | --- | --- | --- |
| `docs/specs/m1-hardening.md` | считает исполнитель (`spec_sha256`) | — | untracked, закоммитить с работой, не править |
| `docs/specs/checks/m1_chart_check.py` | `2fd73f5f8b129011e147ef8f63d35a90c284da7baede13c12c1abb3c94c17b67` | 7376 | untracked, закоммитить с работой, не править |

Образы `alpine/helm:4.3.1` (свежий stable Helm v4.3.1 от 15.10.2026) и слои `anticaptcha:m1` уже на хосте.
Правила авторевью — `$HOME/.claude/skills/executor-milestone/docs/cross-review-v1.md` (в клоне его нет).

## Задача и почему

Сервис публичный по HTTPS, клиентские ключи выдаёт админ. API (FastAPI, `app/`) и воркер
(`python -m workers.task_worker`) делят SQLite (WAL) на томе RWO; чарт `chart/` — два Deployment (api, worker).
Ревью нашло пять дефектов устойчивости и безопасности:

1. **PNG/JPEG-бомба.** `image_text` декодирует клиентскую картинку без предела размеров: однотонный PNG
   20000×20000 весит ~1,2 МБ (base64 ~1,6 МБ, проходит лимит тела 5 МБ), а декод плюс предобработка съедают
   ~4,1 ГБ — воркер с лимитом 4 GiB убивает OOM-killer.
2. **Воркер не создаёт таблицы.** На свежем томе (API ещё не стартовал) воркер падает `no such table: tasks`.
3. **Мёртвый Chromium не пересоздаётся.** Упавший браузер остаётся в кэше `BrowserManager`, все URL-задачи
   падают до рестарта пода. Liveness у воркера нет вовсе.
4. **Prompt injection в агента с инструментами.** Vision LLM — CLI `qwen` с `--approval-mode auto` на картинке
   со страницы, которую целиком контролирует атакующий; временные `captcha_*.png` не удаляются.
5. **Админ-токен у воркера.** Воркер (первым компрометируется через Chromium) получает
   `ANTICAPTCHA_ADMIN_TOKEN` двумя путями: общий `existingSecret` в envFrom и дефолтный `env` чарта.

Плюс мелочь: версия в `app/main.py` захардкожена `1.0.0`, а релиз — 1.0.1.

Что сломается и чинится в этой же вехе: `tests/test_worker_restart.py::test_run_recovers_before_solvers_and_loop`
проверяет порядок вызовов `run()`; после добавления `init_db()` его можно ДОПОЛНИТЬ (не ослабить) этим шагом.
`tests/test_image_text_timeout.py` подменяет `_preprocess_image` и шлёт не-картинку `aGVsbG8=` — проверка размеров
обязана жить ВНУТРИ `_preprocess_image`, иначе этот тест упадёт.

## Что проверено вживую, а что предположение

Проверено постановщиком 10.11.2026 на BASE (клон от `5b2aa40`, образ собран из него):

- Полный набор: команда из «Где работать» на всём `tests` → `126 passed` за ~6 с (и с монтированием `app/`,
  `workers/`, и без него).
- `workers/solvers/image_text.py`: `_ocr` (стр. 80–87) делает `base64.b64decode` (81) → `_preprocess_image` (82) →
  `cv2.imdecode(..., IMREAD_COLOR)` (104–105) без проверки размеров; `None` → `ValueError("Failed to decode image")`.
  `solve` (53–78) гонит `_ocr` в однопоточном executor'е. Ошибка солвера → `process_task` ставит `failed` с
  `str(e)` (`workers/task_worker.py`, стр. 107–115). Лимит тела — `app/config.py:24` `max_body_bytes = 5 MiB`.
- Бомба: PNG 20000×20000 RGB, сжатый построчно zlib-9, — 1 166 428 байт; `imdecode` + цепочка предобработки в
  образе под `docker --memory 4g` — `maxrss 4110 MB`. OOM полного воркера (с torch и моделями) — вывод из этого
  замера, сам OOM не воспроизводился.
- Pillow 13.0.0 в образе есть (транзитивно, в `requirements.txt` не закреплён). `Image.open(BytesIO)` читает
  размер из заголовка без декода: PNG с IHDR 5000×5000 и крошечным IDAT (69 байт) → `(5000, 5000)`; 4097×10 →
  `(4097, 10)`; 20000×20000 PNG и JPEG с переписанным SOF0 → `DecompressionBombError` прямо в `open`
  (порог Pillow 2×`MAX_IMAGE_PIXELS` = 178 956 970); `b"hello"` → `UnidentifiedImageError`; `cv2.imdecode` на
  усечённом заголовке 20000×20000 возвращает `None`.
- Клиентская картинка декодируется ТОЛЬКО в `image_text`: API принимает пять типов (`app/schemas/task.py:8–14`),
  реестр воркера — те же пять (`workers/task_worker.py:21–27`); `app/` картинки не декодирует (grep `imdecode`,
  `Image.open`, `b64decode`). Прочие декоды — скриншоты Chromium, а не байты клиента: `recaptcha.py:195,239,242`
  → `Image.open` (296); `classifiers/yolo.py:116,242` — из `HybridClassifier` незарегистрированного `unified`.
  Они вне вехи.
- `workers/task_worker.py`: импорт `from app.database import SessionLocal` (стр. 6), `run()` (160) первым делом
  зовёт `recover_interrupted_tasks()` (163), затем `setup_solvers()` (166), цикл опроса 170–189.
  `app/database.py:45–48` `init_db()` — идемпотентный `create_all` с импортом `app.models`. Вживую: воркер на
  пустом `ANTICAPTCHA_DATABASE_PATH` → `OperationalError: no such table: tasks`, rc 1 за ~3 с.
- `setup_solvers` в образе на этом хосте — ~5 с (EasyOCR, YOLO, без сети); Chromium запускается лениво.
- `app/utils/browser.py`: `get_browser` (22–48) — `if not self._browser:` стартует `async_playwright()` и
  `chromium.launch`; живость браузера не проверяется; `close()` (76–88); глобальный `browser_manager` (92) берут
  `recaptcha.py:100,540`, `hcaptcha.py:57`, `turnstile.py:46`. Playwright 1.40.0: `Browser.is_connected() -> bool`
  и `Browser.on("disconnected", cb)` есть (сигнатуры сняты `inspect` в образе).
- `workers/classifiers/vision_llm.py`: `classify_tiles` (48–84) пишет `captcha_<id>.png` в `self.temp_dir`
  (69–73) и не удаляет; `cleanup()` (350–354) из `recaptcha.py` не вызывается. Команда (148–156):
  `qwen -m <model> "Analyze the CAPTCHA image at <path>. <prompt>" --json-schema @<schema> --output-format json
  --approval-mode auto --max-wall-time 60s`, env с `QWEN_CODE_SUPPRESS_YOLO_WARNING` (161–164). Инструкция
  (`target` со страницы) тоже идёт в промпт (`recaptcha.py:248`). Разбор вывода — 185–291.
- CLI `qwen` 0.27.1 (`Dockerfile:40`, `qwen --help` в образе): `--approval-mode plan|default|auto-edit|auto|yolo`,
  `--max-tool-calls` («0 — ни одного вызова, `structured_output` под `--json-schema` не считается», превышение →
  rc 55), `--core-tools`, `--exclude-tools`, `--include-directories`, `--bare`, `--safe-mode`.
- Поведение CLI проверено против ФЕЙКОВОГО OpenAI-совместимого сервера (Docker, internal-сеть, копия
  `config/qwen/settings.json` с `baseUrl` на фейк; ключа нет):
  - текущая команда отдаёт модели инструменты `glob, grep_search, read_file, skill, tool_call, tool_search`
    (через `tool_call` достижимы `agent`, `web_fetch`, `cron_*` и др.), картинку в первом запросе НЕ шлёт
    (модель должна сама звать `read_file`), а после ответа запускает второй запрос — субагент извлечения
    памяти с `read_file, grep_search, write_file, edit`;
  - `@<абсолютный путь>` в промпте вместе с `--include-directories <каталог файла>` вставляет картинку прямо в
    первый запрос (`image_url`, data URI); без `--include-directories` файл вне рабочего каталога не вставляется.
    Точка или перевод строки сразу после пути вставке не мешают;
  - `--core-tools structured_output` + `--exclude-tools skill tool_call tool_search agent get_goal update_goal
    report_findings enter_worktree exit_worktree record_artifact list_agents send_message task_stop` → в запросе
    РОВНО один инструмент `structured_output`; поодиночке каждый флаг оставляет лишнее;
  - `memory.enableManagedAutoMemory: false` и `memory.enableManagedAutoDream: false` в `settings.json` убирают
    второй запрос (субагент памяти с `write_file`/`edit`);
  - с этим набором плюс `--approval-mode plan --max-tool-calls 0`: ответ `structured_output({"indices":[0,3]})`
    → rc 0 и `"structured_result":{"indices":[0,3]}` в выводе (текущий парсер это читает); ответ-вызов
    `run_shell_command` или `read_file` → rc 55, инструмент не исполнен (файл-маркер не создан);
  - `--bare` и `--safe-mode` отбрасывают `settings.json` → «No auth type is selected»: НЕ использовать.
- Чарт: `chart/templates/deployment.yaml` — api env/envFrom стр. 46–58, worker 128–140, оба берут
  `.Values.env` и `.Values.existingSecret`; `chart/values.yaml:81` `existingSecret: ""`, дефолтный `env` (84–104)
  несёт `ANTICAPTCHA_ADMIN_TOKEN` и `BAILIAN_CODING_PLAN_API_KEY` через `secretKeyRef` — `helm template` на BASE
  показывает админ-токен в env воркера. `helm lint` (alpine/helm:4.3.1) на BASE — rc 0.
- `app/main.py:27` `version="1.0.0"`, `:55` `"version": "1.0.0"`; `chart/Chart.yaml` `appVersion: "1.0.1"`;
  `app/__init__.py` пуст. Образ кладёт в `/app` только `app/`, `workers/`, `init_db.py`, `run_worker.py`
  (`Dockerfile:87–89`), поэтому `chart/` и `config/` тесты видят только через монтирование.
- Выполнимость проверена: набросок чартовой части даёт `PASS` чекера AC-006; набросок `workers/heartbeat.py` +
  `init_db()` в `run()` проходит команду AC-007 за ~8 с. Наброски удалены.

**Предположения (живьём не проверить — ключа LLM нет):** настоящая `kimi-k2.5` через DashScope принимает
картинку как `image_url` в сообщении пользователя и отвечает вызовом `structured_output` так же, как раньше
через результат `read_file`. Порог `maxAgeSeconds: 300` и бюджет startupProbe 600 с — с запасом над
`task_timeout` 120 с и ~5 с старта на этом хосте; на медленном CPU не мерены.

## Что сделать

### 1. Предел размеров картинки (`workers/solvers/image_text.py`, `app/config.py`)

- В `Settings`: `max_image_pixels: int = 4_000_000`, `max_image_side: int = 4096`
  (env `ANTICAPTCHA_MAX_IMAGE_PIXELS`, `ANTICAPTCHA_MAX_IMAGE_SIDE`).
- Функция уровня модуля `check_image_dimensions(image_bytes: bytes) -> tuple[int, int]`: размер из заголовка
  через `PIL.Image.open(io.BytesIO(...))` БЕЗ `load()`; лимиты читаются из `settings` в момент вызова. Отказ —
  `ValueError` с текстом, начинающимся с `Image too large:` (при `width*height > max_image_pixels` ИЛИ
  `max(width, height) > max_image_side`; равенство пропускается), в том числе на `DecompressionBombError`; любая
  иная ошибка открытия → `ValueError`, начинающийся с `Unsupported or corrupt image`.
- Вызов — первой строкой `_preprocess_image`, ДО `np.frombuffer`/`cv2.imdecode`. Остальную предобработку не менять.

### 2. Старт воркера (`workers/task_worker.py`)

- Импорт `from app.database import SessionLocal, init_db`; в `run()` первым шагом `init_db()` (через имя модуля,
  чтобы тесты могли подменить `task_worker.init_db`), затем `recover_interrupted_tasks()` в `try/except Exception`
  с логом `⚠️ Recovery of interrupted tasks failed: <тип>: <текст>` и продолжением. Сбой самого `init_db()` воркер
  роняет (без таблиц работать нечем).

### 3. Браузер (`app/utils/browser.py`)

- `get_browser`: если закэшированный браузер есть, но `is_connected()` ложно — сбросить его (и `_context`) и
  запустить новый. Новый браузер — через уже запущенный `self._playwright`; второй `async_playwright().start()` —
  только если драйвера нет. Сразу после запуска — `browser.on("disconnected", <обработчик>)`; обработчик
  сбрасывает `_browser`/`_context`, только если отвалился именно текущий браузер.
- Если `chromium.launch` бросил исключение — best-effort `self._playwright.stop()`, `self._playwright = None`,
  исключение пробросить: следующий вызов поднимет драйвер заново. Публичные методы и их сигнатуры не менять.

### 4. Heartbeat и liveness воркера (`workers/heartbeat.py` — новый, `workers/task_worker.py`, `app/config.py`)

- В `Settings`: `worker_heartbeat_file: str = "/tmp/worker-heartbeat"`, `worker_heartbeat_interval: float = 10.0`.
- `workers/heartbeat.py`: `beat(path)` — пишет `time.time()` текстом атомарно (временный файл рядом +
  `os.replace`); `is_fresh(path, max_age, now=None) -> bool` — нет файла / не число / старше `max_age` → `False`;
  `async heartbeat_loop(path, interval)` — `beat` и `asyncio.sleep(interval)` в цикле, ошибка записи логируется
  и не роняет цикл; CLI `python -m workers.heartbeat --check --max-age N [--path P]` → rc 0 свежий, 1 иначе;
  путь по умолчанию — `settings.worker_heartbeat_file`.
- В `run()`: после `setup_solvers()` — `asyncio.create_task(heartbeat_loop(...))` с путём и интервалом из
  `settings` в момент вызова; задача живёт, пока идёт цикл (и во время `process_task`, до `task_timeout`), и
  отменяется в `finally` при выходе из `run()` — в том числе по исключению.

### 5. Песочница vision LLM (`workers/classifiers/vision_llm.py`, `config/qwen/settings.json`)

- Команда `_call_qwen_cli` — ровно в таком порядке (прошла проверку против фейкового сервера):
  `["qwen", "-m", <model>, <промпт>, "--include-directories", str(self.temp_dir), "--json-schema", f"@{schema}",
  "--output-format", "json", "--approval-mode", "plan", "--max-tool-calls", "0", "--core-tools",
  "structured_output", "--exclude-tools", *EXCLUDED_TOOLS, "--max-wall-time", "60s"]`, где промпт содержит
  `@<абсолютный путь картинки>`, за которым идёт пробел, точка, перевод строки или конец строки, а
  `EXCLUDED_TOOLS` — константа модуля из 13 имён раздела «Что проверено». В argv нет `auto`, `auto-edit`, `yolo`,
  `--yolo`, `-y`; `QWEN_CODE_SUPPRESS_YOLO_WARNING` из env убрать. Комментарии про `--yolo`/`auto` переписать.
- `classify_tiles`: временный `captcha_*.png` удаляется в `finally` (`unlink(missing_ok=True)`) при любом исходе.
- `config/qwen/settings.json`: добавить `"memory": {"enableManagedAutoMemory": false, "enableManagedAutoDream": false}`,
  остальное не трогать. Разбор вывода (185–291) не менять.

### 6. Секреты и probe воркера в чарте (`chart/templates/deployment.yaml`, `chart/values.yaml`, `chart/README.md`)

Оба Deployment остаются в `deployment.yaml`; api-часть не меняется. Новые values (дефолты дословно):

```yaml
worker:
  existingSecret: ""          # пусто — как раньше, общий existingSecret
  heartbeatFile: /tmp/worker-heartbeat
  livenessProbe:
    enabled: true             # false убирает и livenessProbe, и startupProbe воркера
    maxAgeSeconds: 300
    periodSeconds: 30
    timeoutSeconds: 10
    failureThreshold: 3
  startupProbe:
    periodSeconds: 10
    timeoutSeconds: 10
    failureThreshold: 60
```

- envFrom воркера: `secretRef` на `worker.existingSecret`, если задан, иначе на `existingSecret` (если задан).
- env воркера: `.Values.env` БЕЗ записей с `name: ANTICAPTCHA_ADMIN_TOKEN` плюс
  `ANTICAPTCHA_WORKER_HEARTBEAT_FILE` = `worker.heartbeatFile`.
- При `enabled`: `startupProbe` и `livenessProbe` воркера —
  `exec: ["python", "-m", "workers.heartbeat", "--check", "--max-age", "<maxAgeSeconds>"]` с периодами из values.
  startupProbe закрывает загрузку моделей (heartbeat стартует после `setup_solvers`), `initialDelaySeconds` не нужен.
- Чекер постановщика `docs/specs/checks/m1_chart_check.py` проверяет ровно это; `chart/README.md` — описать ключи.

### 7. Версия (`app/__init__.py`, `app/main.py`)

`__version__ = "1.0.1"` в `app/__init__.py`; `FastAPI(version=__version__)` и `"version": __version__` в `/`.
Версии чарта и приложения НЕ бампать — релиз отдельно.

### 8. Тесты (имена дословно; каждый ассерт, на который опирается мутация, — с сообщением)

- `tests/test_image_limits.py`: `test_png_bomb_rejected_before_decode`, `test_jpeg_bomb_rejected_before_decode`
  (20000×20000; PNG — IHDR + крошечный IDAT, JPEG — маленький JPEG от Pillow с переписанным SOF0; бинарники в
  репо не класть), `test_pixel_limit_without_side_limit` (3000×3000), `test_side_limit_without_pixel_limit`
  (4097×10), `test_limits_configurable` (лимиты через `monkeypatch` на `settings`: 11×10 отказ, 10×10 проходит),
  `test_corrupt_header_fails` (`aGVsbG8=`), `test_normal_image_still_decoded` (настоящий PNG ~200×60).
  Задачи гнать через `TaskWorker.process_task` с настоящим `ImageTextSolver`, у которого `cv2` — обёртка-счётчик
  над настоящим `cv2`, а `reader` — фейк: при отказе `status == "failed"`, `error_message` с нужным префиксом,
  `imdecode` вызван 0 раз; у нормальной — 1 раз.
- `tests/test_worker_startup.py`: `test_run_on_fresh_database_creates_tables` (subprocess с
  `ANTICAPTCHA_DATABASE_PATH` на новый файл в `tmp_path`, `setup_solvers` подменён исключением-остановкой;
  rc 0 и таблица `tasks` в файле), `test_recovery_error_does_not_stop_worker` (`recover_interrupted_tasks` бросает
  `sqlalchemy.exc.OperationalError` → `run()` доходит до `setup_solvers`), `test_init_db_before_recovery` (порядок
  `init_db` → recover → setup).
- `tests/test_heartbeat.py`: `test_heartbeat_updates_during_long_task` (интервал 0.05 с через `settings`, файл в
  `tmp_path`, солвер ждёт ~1 с через `asyncio.sleep`; значение в файле за время задачи выросло минимум трижды),
  `test_check_detects_stale_and_missing` (свежий → 0, старше max-age → 1, нет файла → 1, мусор → 1 — через
  `main([...])`), `test_heartbeat_task_cancelled_on_exit` (после выхода `run()` по исключению задача heartbeat
  отменена).
- `tests/test_browser_reconnect.py` (фейковый `async_playwright` через `monkeypatch`, без настоящего Chromium):
  `test_disconnected_browser_is_relaunched`, `test_disconnect_event_resets_cached_browser` (событие сброса при
  `is_connected()` всё ещё `True`), `test_connected_browser_is_reused`, `test_launch_failure_restarts_driver`; во
  всех — драйвер стартует ровно столько раз, сколько требует п. 3.
- `tests/test_vision_llm_sandbox.py` (`asyncio.create_subprocess_exec` подменён, процесс фейковый):
  `test_qwen_command_is_tool_free` (значения после `--approval-mode`, `--max-tool-calls`, `--core-tools`; набор
  после `--exclude-tools` равен 13 именам; `--include-directories` == `temp_dir`; `@<путь>` в промпте; запрещённых
  токенов нет), `test_temp_image_removed_after_success`, `test_temp_image_removed_after_failure` (подпроцесс падает
  или таймаут), `test_qwen_settings_disable_memory_agent` (читает `config/qwen/settings.json` от корня репо;
  нет файла — тест ПАДАЕТ, не skip).
- `tests/test_version.py`: `test_root_version_matches_chart_app_version` (`/`, `app.version` и `__version__`
  равны `appVersion` из `chart/Chart.yaml`; нет файла — падение, не skip).
- `tests/test_worker_restart.py` — только дополнить ожидаемый порядок шагом `init_db`, если тест того требует.

### 9. Мутационные ворота (`tests/mutation_gate_m1.py`, коммитится с работой)

Запуск `python3 tests/mutation_gate_m1.py <группа> [<группа> …]` на хосте, только stdlib. Один раз в начале —
`docker build -q -t anticaptcha:m1 .`. На каждую мутацию строго по порядку: (1) сохранить байты файла и sha256;
(2) прогнать ЦЕЛЕВОЙ тест на чистом дереве командой из «Где работать» с `-rf` — обязан пройти, иначе мутация
не засчитана; (3) убедиться, что заменяемый фрагмент встречается в файле РОВНО один раз; (4) наложить замену и
прогнать тот же узел; (5) в `finally` вернуть байты и сверить sha256; (6) мутант убит, если тест прошёл на чистом,
pytest на мутанте вернул rc 1, в строке `FAILED <узел> - …` сводки `-rf` есть заданная мутацией подстрока `expect`.
`expect` — текст сообщения ассерта самого теста (или `DID NOT RAISE`), не имя исключения краха (`ImportError`,
`SyntaxError`, `NameError`, `AttributeError`, `TypeError`). Печать по мутации: `KILLED`/`SURVIVED`/`INVALID` и
первая строка падения; rc 0 — только если убиты все мутации запрошенных групп. Минимальный набор (точные
фрагменты выбирает исполнитель по своему коду):

| Группа | Id | Мутация | Целевой тест |
| --- | --- | --- | --- |
| image | IMG-1 | убран вызов `check_image_dimensions` из `_preprocess_image` | `test_png_bomb_rejected_before_decode` |
| image | IMG-2 | выключено сравнение по числу пикселей | `test_pixel_limit_without_side_limit` |
| image | IMG-3 | выключено сравнение по стороне | `test_side_limit_without_pixel_limit` |
| image | IMG-4 | лимиты — литералы вместо `settings` | `test_limits_configurable` |
| image | IMG-5 | ошибка разбора заголовка проглатывается, идёт декод | `test_corrupt_header_fails` |
| worker | WRK-1 | убран вызов `init_db()` из `run()` | `test_run_on_fresh_database_creates_tables` |
| worker | WRK-2 | снят `try/except` вокруг recovery | `test_recovery_error_does_not_stop_worker` |
| worker | HB-1 | цикл heartbeat пишет файл только один раз | `test_heartbeat_updates_during_long_task` |
| worker | HB-2 | `is_fresh` всегда `True` | `test_check_detects_stale_and_missing` |
| browser | BR-1 | убрана проверка `is_connected()` | `test_disconnected_browser_is_relaunched` |
| browser | BR-2 | не регистрируется обработчик `disconnected` | `test_disconnect_event_resets_cached_browser` |
| browser | BR-3 | проверка `is_connected()` инвертирована | `test_connected_browser_is_reused` |
| vision | VIS-1 | убрана пара `--max-tool-calls 0` | `test_qwen_command_is_tool_free` |
| vision | VIS-2 | `plan` → `auto` | `test_qwen_command_is_tool_free` |
| vision | VIS-3 | из `EXCLUDED_TOOLS` выпал `tool_call` | `test_qwen_command_is_tool_free` |
| vision | VIS-4 | убрана пара `--include-directories` | `test_qwen_command_is_tool_free` |
| vision | VIS-5 | убрано удаление временного файла | `test_temp_image_removed_after_failure` |
| vision | VIS-6 | `enableManagedAutoMemory` → `true` в `settings.json` | `test_qwen_settings_disable_memory_agent` |
| version | VER-1 | версия в `/` — литерал `"1.0.0"` | `test_root_version_matches_chart_app_version` |

### 10. Документы

`CHANGELOG.md` — секция `## [Unreleased]` сверху (Fixed/Security/Added: что и почему, имена env и values);
`docs/specs/limits.md` — лимиты картинки и heartbeat. `docs/STATE.md`, `README.md` — по желанию.

## Не трогать

`requirements*.txt` и версии зависимостей (Playwright обновляется в следующей вехе), `Dockerfile*`, `.github/`,
`app/api/**` и `app/schemas/**` (контракт `/api/v1/*`), `app/body_limit.py`, `workers/solvers/url_guard.py`, все
солверы кроме `image_text.py`, `workers/classifiers/yolo.py`, существующие тесты кроме дополнения из п. 8, api-часть
чарта. Эту спеку и чекер не править, но ЗАКОММИТИТЬ вместе с работой (`docs/specs/m1-hardening.md`,
`docs/specs/checks/m1_chart_check.py`). Полный список разрешённых путей — в команде AC-008.

## Разрешения

Docker под своим пользователем (`docker build`, `docker run` с read-only монтированием клона), сеть — для сборки
образа; временные каталоги `mktemp -d`; коммиты в `m1-hardening`; запуск чекера и ворот. Запрещено: `git push`,
`sudo`, установка на хост, `docker system prune`, правка файлов вне клона, host tmux и чужие процессы.

## Критерии приёмки

Команды запускаются из корня клона; приёмщик зовёт их через `/bin/sh`, поэтому всё в `bash -c '…'`.

- **AC-001 — образ собирается, весь набор тестов зелёный в нём.**
  `bash -c 'docker build -q -t anticaptcha:m1 . >/dev/null && docker run --rm --network none -v "$PWD/tests:/app/tests:ro" -v "$PWD/chart:/app/chart:ro" -v "$PWD/config:/app/config:ro" anticaptcha:m1 python -m pytest tests -q -p no:cacheprovider'`

- **AC-002 — мутации предела картинки убиты своими тестами.**
  `bash -c 'python3 tests/mutation_gate_m1.py image'`

- **AC-003 — мутации старта воркера и heartbeat убиты своими тестами.**
  `bash -c 'python3 tests/mutation_gate_m1.py worker'`

- **AC-004 — мутации пересоздания браузера убиты своими тестами.**
  `bash -c 'python3 tests/mutation_gate_m1.py browser'`

- **AC-005 — мутации песочницы vision LLM и версии убиты своими тестами.**
  `bash -c 'python3 tests/mutation_gate_m1.py vision version'`

- **AC-006 — чарт: секрет воркера, нет админ-токена у воркера, probe по heartbeat, lint.**
  `bash -c 'echo "2fd73f5f8b129011e147ef8f63d35a90c284da7baede13c12c1abb3c94c17b67  docs/specs/checks/m1_chart_check.py" | sha256sum -c - && python3 docs/specs/checks/m1_chart_check.py'`

- **AC-007 — живой старт: воркер на пустой базе поднимается, heartbeat свежий.**
  `bash -c 'docker build -q -t anticaptcha:m1 . >/dev/null && docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/fresh/anticaptcha.db -e ANTICAPTCHA_WORKER_HEARTBEAT_FILE=/tmp/hb anticaptcha:m1 sh -c "python -m workers.task_worker > /tmp/w.log 2>&1 & w=\$!; for i in \$(seq 120); do sleep 1; kill -0 \$w || break; python -m workers.heartbeat --check --max-age 30 && kill \$w && exit 0; done; tail -n 20 /tmp/w.log; exit 1"'`

- **AC-008 — вне разрешённых путей ничего не изменено (коммиты, правки, untracked).**
  `bash -c 'export LC_ALL=C && d=$(mktemp -d) && printf "%s\n" CHANGELOG.md README.md app/__init__.py app/config.py app/main.py app/utils/browser.py chart/README.md chart/templates/deployment.yaml chart/values.yaml config/qwen/settings.json docs/STATE.md docs/specs/checks/m1_chart_check.py docs/specs/limits.md docs/specs/m1-hardening.md report-blocked.md report.json tests/mutation_gate_m1.py tests/test_browser_reconnect.py tests/test_heartbeat.py tests/test_image_limits.py tests/test_vision_llm_sandbox.py tests/test_version.py tests/test_worker_restart.py tests/test_worker_startup.py workers/classifiers/vision_llm.py workers/heartbeat.py workers/solvers/image_text.py workers/task_worker.py | sort > "$d/allowed" && { git diff --name-only 5b2aa40281af612cd6d4edbcf4d850b3392436bb && git ls-files --others --exclude-standard; } | sort -u > "$d/changed" && bad=$(comm -23 "$d/changed" "$d/allowed") && echo "outside allowed: $bad" && test -z "$bad"'`

- **AC-009 — всё закоммичено, дерево чистое, обязательные файлы изменены.**
  `bash -c 'export LC_ALL=C && test -z "$(git status --porcelain --untracked-files=all -- . ":(exclude)report.json" ":(exclude)report-blocked.md")" && d=$(mktemp -d) && git diff --name-only 5b2aa40281af612cd6d4edbcf4d850b3392436bb..HEAD | sort > "$d/changed" && printf "%s\n" CHANGELOG.md app/__init__.py app/config.py app/main.py app/utils/browser.py chart/README.md chart/templates/deployment.yaml chart/values.yaml config/qwen/settings.json docs/specs/checks/m1_chart_check.py docs/specs/limits.md docs/specs/m1-hardening.md tests/mutation_gate_m1.py tests/test_browser_reconnect.py tests/test_heartbeat.py tests/test_image_limits.py tests/test_vision_llm_sandbox.py tests/test_version.py tests/test_worker_startup.py workers/classifiers/vision_llm.py workers/heartbeat.py workers/solvers/image_text.py workers/task_worker.py | sort > "$d/required" && miss=$(comm -13 "$d/changed" "$d/required") && echo "missing: $miss" && test -z "$miss"'`

На BASE (проверено постановщиком на клоне со спекой и чекером untracked): AC-001 и AC-008 зелёные; AC-002…AC-005
красные (`can't open file … tests/mutation_gate_m1.py`); AC-006 красный (14 проверок чекера, в т. ч. админ-токен
в env воркера и `worker secretRef ['b'], got ['a']`); AC-007 красный (`no such table: tasks` в логе); AC-009 красный
(непустой `git status`).

## Контракт отчёта

`report.json` в корне клона, untracked, схемы v2; имена полей дословные; ровно 9 записей в `criteria`
(AC-001…AC-009); `command` посимвольно равна команде критерия этой спеки.

```json
{"schema_version": 2,
 "policy_id": "cross-review-v1",
 "handoff_status": "ready",
 "executor": {"backend": "qwen|spark|codex", "model": "<точная модель>"},
 "spec_sha256": "<sha256 файла docs/specs/m1-hardening.md>",
 "base_sha": "5b2aa40281af612cd6d4edbcf4d850b3392436bb",
 "reviewed_sha": "<коммит, отданный на ревью>",
 "final_sha": "<HEAD клона после единственного захода исправлений>",
 "review": {"initial_receipts": [], "verification_receipts": [], "resolutions": []},
 "criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда критерия>", "rc": 0, "note": "…"}]}
```

Поле — `reviewed_sha`; три sha — 40 строчных hex, цепочка base → reviewed → final. `blocked` — среда не даёт
выполнить критерий (нет Docker, не собирается образ из-за сети): `"rc": null`, дословная ошибка в `note`.
Подмена окружения и глушители кода возврата (`|| true`, `set +e`, `--no-deps`, `--break-system-packages`, `sudo`,
`git push`) запрещены. `resolutions` — как в правилах `cross-review-v1` (`fixed` с `fix_commits` и `proof`,
`disproved` с `proof`, `needs_owner`). Перед сдачей —
`python3 $HOME/.claude/skills/executor-milestone/scripts/accept_run.py "$PWD" --spec docs/specs/m1-hardening.md --dry-run`
до кода 2 (`validation_only`).

## Контракт на невыполнимое

Стоп и `report-blocked.md` в корне клона (команда, её вывод, файл:строка), `handoff_status: blocked`, если:
утверждение раздела «Что проверено» не подтверждается кодом; `qwen` в собранном образе ведёт себя иначе
(флаг отвергнут, лишний инструмент в запросе); мутацию нельзя убить без правки файла из «Не трогать» или без
ослабления поведения; критерий невыполним без пути вне AC-008; образ не собирается. Менять команды критериев,
мутации из таблицы, чекер, пороги и дефолты values ради зелёного — запрещено; «не смог убить» эквивалентным
мутантом не считается.

## Автономное перекрёстное ревью (авторевью)

Действует `cross-review-v1` целиком (`$HOME/.claude/skills/executor-milestone/docs/cross-review-v1.md`). Пара по
backend исполнителя: Codex/Spark → `agy` + `qwen`; Qwen → `codex` + `agy`. Оба ревью параллельно, на
`BASE_SHA..REVIEW_SHA`, только чтение, не показывая чужих находок; эксперименты с процессами — только в Docker с
фейками. Квитанции пишет только обёртка, путь абсолютный, `--base` одинаковый в обеих фазах:
`bash $HOME/.claude/skills/executor-milestone/scripts/review_run.sh initial <ревьюер> --clone "$PWD" --base 5b2aa40281af612cd6d4edbcf4d850b3392436bb --range 5b2aa40281af612cd6d4edbcf4d850b3392436bb..<REVIEW_SHA> --context "<контекст; только чтение>"`
(фаза `verify` — диапазон `<REVIEW_SHA>..<FINAL_SHA>`). Один заход исправлений, дальше `needs_owner`. Код под
исключения ревью не прятать (исключений нет).

## Стыки с соседними вехами

Следующая веха (M2) обновляет Playwright и зависимости: она опирается на то, что `BrowserManager` пересоздаёт
браузер по `is_connected()`/`disconnected`, а liveness воркера держится на `workers.heartbeat`. Не входит сюда:
выпуск релиза и бамп версий, деплой и проверка на живом стенде (за постановщиком), лимит размеров для скриншотов
Chromium в recaptcha, сужение env подпроцесса `qwen`.
