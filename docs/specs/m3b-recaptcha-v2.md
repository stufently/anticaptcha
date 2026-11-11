# M3b — reCAPTCHA v2: кроп плиток, раунды, динамическая сетка

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-11
- **BASE_SHA:** `209578bace27487e7f8f9594f3f887e41af5b764` — конец вехи M3a
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m3b-recaptcha-v2` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only. Юнит-тесты — без сети:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m3b/a.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m3b && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
  E2E — то же без `--network none` и с `-e ANTICAPTCHA_E2E=1`.
- Постановщик кладёт untracked чекер `probes/m3b_check.py` (НЕ коммитить, НЕ править, НЕ удалять). Эту спеку —
  `docs/specs/m3b-recaptcha-v2.md` — закоммитить с работой.

## Задача и почему

Ресерч 11.11 на демо Google (`https://www.google.com/recaptcha/api2/demo`, датацентровый IP): после клика по чекбоксу
Google всегда выдаёт картиночный челлендж, и `RecaptchaV2Solver` (`workers/solvers/recaptcha.py`) его не решает:

1. **Кроп плиток (главный баг).** `_solve_image_challenge_hybrid` скриншотит `tile.locator('img')`, а у reCAPTCHA
   `img.rc-image-tile-33` — спрайт всей сетки 378x378, сдвинутый внутри обёртки 126x126. «Плитка» = вся сетка,
   классификатор видит объект везде и выбирает все 9 (замер: обёртка 126x126, img 378x378).
2. **Один раунд.** После verify токен проверяется один раз через 3 с. Нет повторных раундов, нет реакции на
   `.rc-imageselect-error-select-more` / `.rc-imageselect-error-dynamic-more` / `.rc-imageselect-incorrect-response`.
3. **Динамическая сетка** («Click verify once there are none left»): кликнутые плитки заменяются новыми, нужен цикл
   до пустого выбора, а не один проход.
4. **Цель челленджа** — из фиксированного списка 15 слов (`_extract_target`); неизвестное слово → `ValueError`. Текст
   цели есть в `<strong>` инструкции.

## Что проверено вживую, а что предположение

- Проверено постановщиком (ресерч 11.11): размеры обёртки/img выше; инструкции «Select all images with a fire
  hydrant / Click verify once there are none left» и «Select all squares with motorcycles»; после пустого verify виден
  `error-select-more`; тестовый ключ `6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI` проходит без челленджа.
- Предположение: классы `.rc-imageselect-desc-wrapper strong` / `.rc-imageselect-instructions strong`, `.rc-image-tile-44`
  для 4x4 и замена плиток в динамической сетке (по описаниям в открытых решателях; вживую видели только 3x3).
  Поэтому раундовая логика тестируется на поддельном DOM, а не на Google.
- Vision LLM без ключа в образе выключен — в тестах классификатор подменяется заглушкой.

## Что сделать

Всё в `workers/solvers/recaptcha.py`, класс `RecaptchaV2Solver`. Функции работают с «корнем» — объектом с методом
`.locator()` (в бою это `page.frame_locator('iframe[src*="bframe"]')`, в тестах — сама страница с поддельным DOM).

1. **Вход** — `check_browser_input` из `workers/solvers/widget_page.py` (M3a) и режим `render_mode="widget"` через
   `install_widget_page(page, page_url, "recaptcha_v2", site_key)`, как в M3a.
2. **`async def _read_challenge(self, root) -> dict`**: `{"target": <текст из strong>, "instruction": <весь текст>,
   "grid": "3x3"|"4x4", "dynamic": bool}`. `grid` — по числу `.rc-image-tile-wrapper` (9 / 16); `dynamic` — в
   инструкции есть `none left`. Нет `strong` → цель = вся инструкция. `_extract_target` со списком слов удалить.
3. **Кроп для YOLO-фолбэка** — метод `_grab_tile_shots(self, root) -> list[bytes]`, строка ДОСЛОВНО
   `            shot = await tile.screenshot()` (скрин обёртки `.rc-image-tile-wrapper`, не `img`).
4. **Выбор плиток** — `async def _pick(self, root, ch) -> list[int]`: vision LLM (скрин `.rc-imageselect-target`,
   `classify_tiles(shot, f"Select all {ch['target']}", ch['grid'])`), при его ошибке — YOLO по `_grab_tile_shots`.
   Индексы вне диапазона отбрасываются.
5. **Динамическая сетка**: константа ДОСЛОВНО `MAX_DYNAMIC_PASSES = 5`. Пока `dynamic` и выбор не пуст: кликнуть
   выбранные, подождать замены (~1,5–2 с), заново `_pick`; не больше `MAX_DYNAMIC_PASSES` проходов; затем verify.
6. **Раунды**: константа ДОСЛОВНО `MAX_ROUNDS = 5`, цикл ДОСЛОВНО `        for round_no in range(MAX_ROUNDS):`. Раунд:
   `_read_challenge` → выбор (статично — один `_pick` и клики; динамично — п. 5) → `#recaptcha-verify-button` →
   `_wait_round_outcome(page, root, timeout=10)` возвращает `"token"` (непустой `#g-recaptcha-response` на `page`),
   `"retry"` (видна одна из ошибок п. 2 или сменилась инструкция/плитки) или `"timeout"`. `token` → вернуть,
   `retry` → следующий раунд, `timeout` → `RuntimeError("reCAPTCHA v2: no outcome after verify")`. Раунды кончились →
   `RuntimeError("reCAPTCHA v2: challenge not solved in 5 rounds")`.
7. **Чекбокс**: после клика — опрос токена до 6 с вместо фиксированного сна; есть токен → вернуть без челленджа.
8. **Логи**: токен целиком не печатать (как в M3a — только длина).
9. **Тесты.**
   - `tests/test_m3b_unit.py` (без сети, Chromium из образа, `page.set_content` с поддельным DOM bframe и
     `textarea#g-recaptcha-response`; классификатор — заглушка; каждый тест — свой `asyncio.run` с закрытием браузера в
     `finally`). Имена с `B1`…:
     - `test_B1_crop`: 9 обёрток 126x126, в каждой `img.rc-image-tile-33` 378x378 со смещением (спрайт из 9 разных
       сплошных цветов, `data:` PNG, собранный в тесте) → `_grab_tile_shots` даёт 9 картинок ~126x126, у каждой
       доминирует свой цвет (проверка через PIL);
     - `test_B2_two_rounds`: JS поддельного DOM на первый verify показывает новый раунд (другая инструкция), на второй
       — пишет токен → `solve`-цикл возвращает токен, verify нажат 2 раза, клики пришлись на индексы заглушки;
     - `test_B3_select_more`: первый verify с пустым выбором показывает `.rc-imageselect-error-select-more` → новый
       раунд, затем токен;
     - `test_B4_dynamic`: `dynamic` инструкция, заглушка отдаёт `[0,4]`, `[4]`, `[]` → три вызова классификатора до
       первого verify, verify один;
     - `test_B5_rounds_exhausted`: verify всегда даёт `error-select-more` → `RuntimeError` с `5 rounds`;
     - `test_B6_target`: `Select all images with <strong>parking meters</strong>` → `target == "parking meters"`,
       4x4 (16 обёрток `rc-image-tile-44`) → `grid == "4x4"`.
     Раундовый цикл вынести в метод `async def _solve_rounds(self, page, root) -> str`, чтобы тесты звали его напрямую.
   - `tests/test_m3b_e2e.py` (skip без `ANTICAPTCHA_E2E=1`): `test_E7_v2_testkey` — тестовый ключ Google,
     `page_url="https://example.com/"`, `render_mode="widget"` → токен ≥ 100 символов.
10. **Документация**: README — v2 решает челлендж только с включённым vision LLM, на реальных сайтах с датацентрового
    IP успех не гарантирован; `CHANGELOG.md` — `## [Unreleased]`.

## Не трогать

- Всё, кроме: `workers/solvers/recaptcha.py` (только `RecaptchaV2Solver` и его помощники), `tests/test_m3b_unit.py`,
  `tests/test_m3b_e2e.py`, `README.md`, `CHANGELOG.md`, эта спека. Существующие тесты, которые зовут удалённый
  `_extract_target` (если такие есть), — можно поправить под `_read_challenge`; файл добавить в отчёт.
  `probes/` — не править, не коммитить.
- `RecaptchaV3Solver`, классификаторы, SSRF-guard, схемы API — не менять.
- Образ не пересобирать; `docker system prune` и удаление образов запрещены. Демо Google в тестах не дёргать.

## Разрешения

- Docker под своим пользователем; сеть — только для e2e (`E7`). Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный без сети.** Команда: `python3 probes/m3b_check.py green .`
- **AC-002 — предписанный код на месте.** Команда: `python3 probes/m3b_check.py code .`
- **AC-003 — e2e тестового ключа зелёный.** Команда: `python3 probes/m3b_check.py e2e .`
- **AC-004 — мутанты убиты.** Команда: `python3 probes/m3b_check.py mutants .`
- **AC-005 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m3b_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m3b-check/`, удаляется сам). Перед отчётом прогони все пять команд сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно пять записей AC-001…AC-005:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Поддельный DOM не удаётся сделать так, чтобы `tile.screenshot()` давал отдельную плитку, или раундовый цикл требует
менять сигнатуры вне `RecaptchaV2Solver` — не обходи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

После M3b — живой стенд (vision LLM включён) и релиз 1.2.0 постановщиком.
