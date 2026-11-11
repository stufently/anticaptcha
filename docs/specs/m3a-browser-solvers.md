# M3a — Turnstile, hCaptcha, reCAPTCHA v3: рабочие потоки, режим «виджет», отпечаток, логи

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-11
- **BASE_SHA:** `af5707802900780409a193e649c18d78adef630e` — конец вехи M2d
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m3a-browser-solvers` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в уже собранном образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only.
  Юнит-тесты — без сети:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m3a/a.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m3a && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
  E2E — та же команда, но без `--network none` и с `-e ANTICAPTCHA_E2E=1` (нужен выход к Google, hCaptcha, Cloudflare).
- Постановщик кладёт untracked чекер `probes/m3a_check.py` (НЕ коммитить, НЕ править, НЕ удалять). Эту спеку —
  `docs/specs/m3a-browser-solvers.md` — закоммитить с работой.

## Задача и почему

Браузерные солверы 1.1.0 не решают даже тестовые ключи провайдеров. Ресерч 11.11 (вживую, Chromium 158 headless
shell, playwright-stealth 2.0.3) нашёл баги кода:

- **Turnstile** (`workers/solvers/turnstile.py`): iframe виджета теперь в закрытом shadow DOM, CSS-селектор
  `iframe[src*="challenges.cloudflare.com"]` его не видит → 60 с таймаут, хотя токен уже лежит в
  `input[name="cf-turnstile-response"]` (light DOM). Интерактивного клика нет.
- **hCaptcha** (`workers/solvers/hcaptcha.py`): `iframe[src*="hcaptcha"]` находит два фрейма (checkbox и challenge) →
  strict mode violation; кликается `.checkbox`, а элемент — `#checkbox`; фиксированный sleep вместо опроса.
- **reCAPTCHA v3** (`RecaptchaV3Solver` в `workers/solvers/recaptcha.py`): работает, только если страница сама грузит
  `api.js?render=<key>`; иначе `ReferenceError: grecaptcha is not defined`; ожидание `grecaptcha.ready` не ограничено.
- Сайт клиента может закрывать страницу WAF-ом по IP (демо hCaptcha отдаёт 403 датацентру), хотя скрипты провайдера
  доступны. Решение, как у сервисов-аналогов: режим «виджет» — навигация на `page_url` перехватывается
  `page.route` и отдаётся минимальная страница с виджетом и `site_key`; origin для провайдера тот же.
- **Отпечаток**: stealth выдаёт UA Linux, `navigator.platform = "Win32"` и WebGL-строку Mac — противоречие.
- **Логи**: воркер печатает полный токен (`✅ Task N solved: {...}`).

reCAPTCHA v2 (кроп плиток, раунды) — следующая веха M3b, здесь `RecaptchaV2Solver` не трогать.

## Что проверено вживую, а что предположение

Проверено постановщиком (ресерч 11.11, образ `anticaptcha:m2-accept`, документ `https://example.com/` подменён
через `page.route` страницей с виджетом):
- Turnstile: фрейм есть в `page.frames`; опрос `cf-turnstile-response || turnstile.getResponse()` даёт
  `1x00000000000000000000AA` → `XXXX.DUMMY.TOKEN.XXXX` за 1,5 с; `2x00000000000000000000AB` → токена нет;
  `3x00000000000000000000FF` → токен только после клика мышью по координатам контейнера `.cf-turnstile`
  (левая часть, ~30 px от левого края, по вертикальному центру), без клика пусто 12 с.
- hCaptcha: `iframe[src*="frame=checkbox"]` → `#checkbox` → опрос `[name=h-captcha-response]`: ключ
  `10000000-ffff-ffff-ffff-000000000001` → `10000000-aaaa-bbbb-cccc-000000000001` за 0,5 с.
- v3: демо Google решается, если `api.js` на странице есть; на странице без него — `ReferenceError`.
- `Stealth.__init__` (2.0.3) принимает `navigator_platform_override`, `webgl_vendor_override`,
  `webgl_renderer_override` (по умолчанию platform `Win32`).
- SSRF-guard (`validate_page_url`) режет loopback и приватные адреса — для e2e годится только публичное имя
  (`https://example.com/`), страница подменяется, сам сайт не грузится.

Предположение: клик по координатам для `3x…` стабилен между прогонами (на ресерче — один прогон). Если нет —
контракт на невыполнимое.

## Что сделать

1. **`workers/solvers/widget_page.py`** (новый): общий для браузерных солверов модуль.
   - Строка ДОСЛОВНО: `SITE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")`.
   - `def check_browser_input(input_data) -> tuple[str, str, str]`: возвращает `(site_key, page_url, render_mode)`;
     нет `site_key`/`page_url` → `ValueError`; `site_key` не проходит `SITE_KEY_RE` → `ValueError`; `render_mode`
     (необязательный, по умолчанию `"page"`) проверяется строкой ДОСЛОВНО
     `    if render_mode not in ("page", "widget"):` → `ValueError`.
   - `def widget_html(kind: str, site_key: str) -> str` для `kind` ∈ `turnstile`, `hcaptcha`, `recaptcha_v3`
     (и `recaptcha_v2` — шаблон на будущее, солвер v2 его не использует): минимальный HTML со скриптом провайдера
     (`https://challenges.cloudflare.com/turnstile/v0/api.js`, `https://js.hcaptcha.com/1/api.js`,
     `https://www.google.com/recaptcha/api.js?render=<key>` / `api.js`) и контейнером с `data-sitekey`.
     `site_key` к этому моменту уже проверен регуляркой — в HTML он попадает только так.
   - `async def install_widget_page(page, page_url: str, kind: str, site_key: str)`: `page.route` с
     **функцией-предикатом**, а не строкой (строка в Playwright — glob-шаблон, метасимволы расширят совпадение):
     совпадает только URL, равный `page_url` без `#fragment` (fragment в сетевой запрос не попадает) →
     `route.fulfill(status=200, content_type="text/html", body=widget_html(...))`; прочие запросы идут в сеть как есть.
     Предикат — отдельная функция `def widget_route_matcher(page_url: str)` (возвращает callable). Юнит-тест: для
     `page_url="https://example.com/p?a=1#x"` принимает `https://example.com/p?a=1` и не принимает
     `https://example.com/p?a=2`, `https://example.com/p/x`, `https://example.com/p?a=1&b=2`.
2. **Солверы Turnstile, hCaptcha, v3** — в начале `solve` вызывать `check_browser_input`, затем `validate_page_url`
   (как сейчас), при `render_mode == "widget"` — `install_widget_page` до `goto`.
3. **Turnstile** (`turnstile.py`): убрать `wait_for_selector` по iframe. После `goto` — опрос токена (`input` +
   `turnstile.getResponse()`) каждые 0,5 с с общим дедлайном 30 с. Если на 8-й, 14-й и 20-й секунде токена ещё нет —
   метод `_click_checkbox(page)` (не больше трёх попыток за задачу). Клик делается, только когда фрейм
   `challenges.cloudflare.com` есть в `page.frames` и у контейнера виджета (`.cf-turnstile` или родитель скрытого
   `input[name="cf-turnstile-response"]`) ненулевой `bounding_box`; иначе попытка пропускается. Клик — мышью по
   координатам контейнера (~30 px от левого края, по вертикальному центру). Вызов ДОСЛОВНО
   `await self._click_checkbox(page)` встречается в файле один раз (внутри цикла опроса). Нет токена к дедлайну → `RuntimeError("Turnstile token not received within 30s")`.
   `goto` — `timeout=30000`.
4. **hCaptcha** (`hcaptcha.py`): строка ДОСЛОВНО `CHECKBOX_FRAME = 'iframe[src*="frame=checkbox"]'` (модульная
   константа), ждать этот фрейм (`timeout=20000`), клик `#checkbox` внутри него, опрос
   `[name=h-captcha-response]` / `hcaptcha.getResponse()` до 20 с. Нет токена к дедлайну →
   `RuntimeError("hCaptcha token not received within 20s (interactive challenge is not supported)")`;
   `NotImplementedError` убрать.
5. **v3** (`RecaptchaV3Solver`): метод `_has_execute(page)` (`typeof grecaptcha !== "undefined" && typeof
   grecaptcha.execute === "function"`). Сначала до 5 с ждать, что `_has_execute` станет истинным сам (страница или
   режим «виджет» уже грузят `api.js` — второй экземпляр скрипта не внедрять). Затем строка ДОСЛОВНО
   `        if not await self._has_execute(page):` — тогда
   `page.add_script_tag(url="https://www.google.com/recaptcha/api.js?render=" + site_key)` и ожидание
   `_has_execute` — ОБА шага под одним `asyncio.wait_for(..., 15)` (`add_script_tag` сам ждёт загрузки скрипта и без
   ограничения висит при зависшей загрузке). `grecaptcha.ready` + `execute` — под `asyncio.wait_for(..., 20)`. Ошибки JS и таймауты →
   `RuntimeError` с коротким текстом (`"reCAPTCHA v3: ..."`), без сырого стека Playwright.
6. **Отпечаток** (`app/utils/browser.py`): создание `Stealth` ДОСЛОВНО (одна строка):
   `        self._stealth = Stealth(navigator_platform_override="Linux x86_64", webgl_vendor_override="Google Inc. (Intel)", webgl_renderer_override="ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)") if HAS_STEALTH else None`
7. **Логи** (`workers/task_worker.py`): строка «solved» ДОСЛОВНО
   `            print(f"✅ Task {task.id} solved: {_redact(result)}")`;
   в `_redact` строки длиннее 16 символов заменяются на `"<N chars>"`, короткие (ответ `image_text`) остаются.
   Последняя строка `_redact` ДОСЛОВНО `    return {k: _redact_value(v) for k, v in result.items()}`. Юнит-тест `U1`
   прогоняет обработку задачи воркером с подменённым солвером, который возвращает токен из 40 символов, и проверяет по
   захваченному stdout (`capsys`), что токена там нет, а `<40 chars>` есть.
8. **Тесты.**
   - `tests/test_m3a_unit.py` (без сети): `check_browser_input` — отказ на пустых полях, на `site_key` с `"`, `<`,
     пробелом, длиной 101, на `render_mode="iframe"`; принимает тестовые ключи всех трёх провайдеров и оба режима;
     `widget_html` содержит ключ и нужный URL скрипта; `_redact` — токен 40 символов скрыт, `"X7K2P"` остался.
     Имена тестов с `U1`.
   - `tests/test_m3a_e2e.py`: модульный `pytestmark` = skip, если `ANTICAPTCHA_E2E != "1"`. Солверы вызываются как
     в воркере (классы из реестра `SOLVERS`, `setup()`/`solve()`/`cleanup()`), `page_url="https://example.com/"`,
     `render_mode="widget"`. Каждый тест — свой `asyncio.run(...)`, и в `finally` внутри того же цикла
     `await browser_manager.close()` (общий `browser_manager` иначе переживёт закрытый event loop, и следующий тест
     зависнет):
     - `test_E1_turnstile_pass`: `1x00000000000000000000AA` → токен `XXXX.DUMMY.TOKEN.XXXX`, < 15 с;
     - `test_E2_turnstile_fail`: `2x00000000000000000000AB` → `RuntimeError`, текст с `30s`, < 40 с;
     - `test_E3_turnstile_interactive`: `3x00000000000000000000FF` → токен-заглушка;
     - `test_E4_hcaptcha_pass`: `10000000-ffff-ffff-ffff-000000000001` → `10000000-aaaa-bbbb-cccc-000000000001`;
     - `test_E5_v3_injects_script`: `render_mode="page"` (на `example.com` нет `api.js`), в тесте `page.route` на
       `https://www.google.com/recaptcha/api.js*` отдаёт поддельный скрипт, где `grecaptcha.ready(cb)` вызывает `cb`, а
       `execute` резолвит строку `FAKE-V3-TOKEN` → результат `{"token": "FAKE-V3-TOKEN"}` (маршрут ставится через
       обёртку `browser_manager.new_page` в тесте; сам `example.com` грузится по сети);
     - `test_E6_fingerprint`: страница от `browser_manager.new_page(stealth=True)`: `navigator.platform` начинается с
       `Linux`, UA содержит `Linux` и не содержит `HeadlessChrome`, `UNMASKED_RENDERER_WEBGL` равен строке из п. 6.
9. **Документация**: README — таблица/раздел типов задач: что работает (Turnstile non-interactive и тестовые ключи,
   hCaptcha только тестовый ключ/без интерактивного челленджа, v3 — токен без гарантии score, v2 — ждёт M3b), поле
   `render_mode` с примером; `CHANGELOG.md` — `## [Unreleased]`. Ничего про инфраструктуру хоста/кластера.

## Не трогать

- Всё, кроме: `workers/solvers/widget_page.py`, `workers/solvers/turnstile.py`, `workers/solvers/hcaptcha.py`,
  `workers/solvers/recaptcha.py` (только `RecaptchaV3Solver`), `app/utils/browser.py` (только создание `Stealth`),
  `workers/task_worker.py` (только `_redact` и строка «solved»), `tests/test_m3a_unit.py`, `tests/test_m3a_e2e.py`,
  `README.md`, `CHANGELOG.md`, эта спека. `probes/` — не править, не коммитить.
- `RecaptchaV2Solver`, SSRF-guard (`url_guard.py`), схемы API — не менять.
- Образ не пересобирать; `docker system prune` и удаление образов запрещены.

## Разрешения

- Docker под своим пользователем; сеть — только для e2e к провайдерам капчи и `example.com`. Не больше ~10 прогонов
  e2e за веху (не нагружать провайдеров). Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный без сети.** Команда: `python3 probes/m3a_check.py green .`
- **AC-002 — предписанный код на месте.** Команда: `python3 probes/m3a_check.py code .`
- **AC-003 — e2e на тестовых ключах зелёные.** Команда: `python3 probes/m3a_check.py e2e .`
- **AC-004 — мутанты убиты.** Команда: `python3 probes/m3a_check.py mutants .`
- **AC-005 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m3a_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m3a-check/`, удаляется сам). Перед отчётом прогони все пять команд сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно пять записей AC-001…AC-005:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

E2E на тестовом ключе нестабилен (проходит не каждый прогон) или провайдер недоступен из контейнера — не ослабляй
проверку, не мокай провайдера в E1–E4, не увеличивай дедлайны сверх спеки: `fail` с объяснением (лог, скриншот в
`tmp/`) и стоп.

## Стыки с соседними вехами

M3b (reCAPTCHA v2: кроп плиток, раунды, сетки) — от HEAD этой вехи, использует `check_browser_input` и
`widget_html("recaptcha_v2", ...)`.
