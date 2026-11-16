# AGENTS.md

Правила для агента в проекте anticaptcha.

## Репозиторий публичный

Сюда не попадает ничего про конкретную инсталляцию: имена кластеров и хостов,
внутренние домены, namespace'ы, пути в хранилищах секретов, реальные IP,
локальные пути пользователей. История не переписывается — попавшее остаётся
навсегда.

## Устройство

- `app/` — FastAPI (`app.main:app`): задачи, пользователи, ключи, статистика;
  CLI администрирования — `python -m app.cli`.
- `workers/task_worker.py` — воркер: берёт задачи из базы, реестр солверов
  `SOLVERS` (типы задач — `TaskType` в `app/schemas/task.py`, тест сверяет одно с
  другим), таймаут задачи, heartbeat для проб, чистка по срокам хранения.
- `workers/solvers/` — солверы; URL-солверы проходят SSRF-guard
  `workers/solvers/url_guard.py`. Файлы `amazon.py`, `cloudflare.py`,
  `funcaptcha.py`, `geetest.py`, `simple_captcha.py`, `tencent.py`, `vk.py`,
  `vk_challenge.py`, `unified.py` — библиотечный интерфейс `solve(page, element)`,
  в реестре воркера их нет.
- База — только SQLite (`ANTICAPTCHA_DATABASE_PATH`), один файл на общем томе
  API и воркера, режим WAL. Воркер — один процесс.
- Настройки — `app/config.py`, переменные с префиксом `ANTICAPTCHA_`; ключ vision
  LLM — `BAILIAN_CODING_PLAN_API_KEY`.
- Образ — `Dockerfile` (Chromium, модели YOLO и EasyOCR внутри образа),
  `ghcr.io/stufently/anticaptcha`; Helm-чарт — `chart/`; локальный запуск —
  `docker-compose.yml` (`DOCKER_COMPOSE.md`).

## Учётные файлы

- `CHANGELOG.md` — каждое изменение: в `[Unreleased]`, разделы
  `### Added|Fixed|Removed — YYYY-MM-DD`. Релиз переименовывает `[Unreleased]` в
  `[X.Y.Z] — YYYY-MM-DD` и открывает пустой `[Unreleased]`.
- `docs/specs/limits.md` — лимиты и ограничения (таймауты, квоты, размеры,
  браузер); менять вместе с кодом, который их задаёт.
- `docs/specs/` — спецификации вех.

## Работа

- Ничего не ставить на хост: тесты и запуск — в Docker, от своего uid
  (`-u $(id -u):$(id -g)`), иначе файлы в bind-mount достанутся root.
- Тесты — в образе, без сети, как в CI (`.github/workflows/images.yml`):

  ```bash
  docker run --rm -u "$(id -u):$(id -g)" --network none -e HOME=/tmp \
    -v "$PWD":/app -w /app ghcr.io/stufently/anticaptcha:<версия> \
    python -m pytest tests -q -p no:cacheprovider
  ```

  Тесты с живыми провайдерами (`tests/test_m3a_e2e.py`, `test_m3b_e2e.py`,
  `test_m4a_e2e.py`) пропускаются без `ANTICAPTCHA_E2E=1`. Остальные браузерные
  тесты используют Chromium образа и локальные страницы через `page.route`.
- Релиз: `version` и `appVersion` в `chart/Chart.yaml`, `__version__` в
  `app/__init__.py`, раздел в `CHANGELOG.md`; затем тег `vX.Y.Z` — workflow
  `Images` сверяет тег с `appVersion`, гоняет тесты в собранном образе и пушит
  образ в GHCR.
- Перед «готово»: тесты зелёные, API отвечает на `/health`, воркер стартует и
  пишет, что солверы готовы.
