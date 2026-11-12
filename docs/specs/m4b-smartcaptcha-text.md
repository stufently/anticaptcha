# M4b — Yandex SmartCaptcha: текстовое задание через vision LLM

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-12
- **BASE_SHA:** `575e2a2e3a352c45a8ec4bdfa1e640303e15624d` — конец вехи M4a
- **Исполнитель:** `cx`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m4b-smartcaptcha-text` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only, без сети:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m4b/a.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m4b && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
- Постановщик кладёт untracked чекер `probes/m4b_check.py` (НЕ коммитить, НЕ править, НЕ удалять). Эту спеку —
  `docs/specs/m4b-smartcaptcha-text.md` — закоммитить с работой.

## Задача и почему

После M4a `SmartCaptchaSolver` (`workers/solvers/smartcaptcha.py`) распознаёт задание и падает в `_solve_challenge`
с `... challenge is not supported yet`. Яндекс с датацентровых адресов выдаёт задание всегда, чаще всего «текст»
(картинка с искривлённой русской фразой + поле ввода). Веха решает текстовое задание через vision LLM. Силуэты и
неизвестные типы по-прежнему завершаются понятной ошибкой: замер дал ~40 % верного порядка до проверки сервером,
это отдельная работа.

## Что проверено вживую, а что предположение

Проверено постановщиком 12.11 (Chromium из образа, датацентровый IP, модель воркера по умолчанию, qwen CLI теми же
флагами песочницы, что в `workers/classifiers/vision_llm.py`):

- DOM задания (внутри `iframe[data-testid="advanced-iframe"]`): корень `.AdvancedCaptcha.AdvancedCaptcha_image`,
  картинка `.AdvancedCaptcha-View img` (src `https://smartcaptcha.yandexcloud.net/load-captchaimg?...`, натуральный
  размер ~248x81), поле `input[name="rep"]`, кнопка `button[data-testid="submit"]`. При неверном ответе — подсказка
  «Попробуйте ещё раз. Дополнительная проверка» в `.Textinput-Hint` и СРАЗУ новая картинка (меняется src).
- Кириллица, набранная `press_sequentially` (key-события), доходит до значения поля без искажений.
- Точность распознавания (24 картинки): на ключах с простыми заданиями 13 из 15, на ключе официальной демки 1 из 9.
  Лучший промпт — дословно в п. 2; ответ модели бывает в верхнем регистре; увеличение картинки не помогает; один
  вызов ~7 с; 1 из 72 вызовов вернул пустой ответ.
- Принимает ли Яндекс верный ответ с датацентрового IP — НЕТ (9 из 9 отклонены, в т. ч. явно верные). Поэтому
  успех вехи проверяется на поддельном DOM; живой токен — только через резидентный прокси на стенде постановщика.

Предположение: проверка ответа нечувствительна к регистру (поэтому вводим строчными).

## Что сделать

1. **Vision LLM — `workers/classifiers/vision_llm.py`.**
   - `_call_qwen_cli(self, image_path, prompt, schema=None)`: `schema=None` → прежняя схема `indices` (поведение
     `classify_tiles` не меняется); иначе в `--json-schema` уходит переданная схема. Остальные флаги песочницы —
     без изменений. Если передана своя схема, а `structured_result` в выводе CLI нет, запасной разбор текста
     ассистента возвращает JSON-объект (из ```json-блока или всего текста), если он разобрался в `dict`; запасные
     ветки для массива `indices` срабатывают только при `schema=None`.
   - Новый метод ДОСЛОВНО `async def read_text(self, image_bytes: bytes) -> str`: выключен (`not self.enabled`) →
     `RuntimeError("Vision LLM is disabled (no API key)")`; картинка во временный файл (удаляется в `finally`, как в
     `classify_tiles`); схема `{"type": "object", "properties": {"text": {"type": "string", "maxLength": 80}},
     "required": ["text"]}`; ответ — `structured_result["text"]`, `strip()`; пусто/нет поля/не строка →
     `ValueError("vision LLM returned no text")`. Текст ответа в лог НЕ пишется (только длина).
2. **Промпт** — константа ДОСЛОВНО (одной строкой в коде):
   `TEXT_PROMPT = "Transcribe the Russian (Cyrillic) words in the CAPTCHA image exactly, letter by letter, in reading order along the curved baseline. Do not translate, do not autocorrect, keep original case, separate words with single spaces. Put only the transcription into the text field."`
3. **Солвер — `workers/solvers/smartcaptcha.py`.**
   - `DEADLINE_SECONDS = 75` (было 60). Бюджет задачи `task_timeout` — 120 с: навигация до 30 с + опрос 75 с +
     остановка qwen CLI при отмене до ~5 с + закрытие страницы — укладывается с запасом. Сообщение дедлайна —
     `SmartCaptcha: no token within 75s` (строится из константы, как уже сделано в M4a).
   - Вызов `read_text` в солвере — тоже через `_bounded` (дедлайн опроса): отмена по дедлайну гасит qwen CLI тем же
     путём, что и раньше (`_reap`).
   - Классификатор — атрибут `self.vision_classifier`: `None` в `__init__`, `VisionLLMClassifier()` в `setup()`;
     `_solve_text` создаёт его сам, если он всё ещё `None` (тесты и вызовы без `setup()`); в тестах подменяется
     заглушкой.
   - `_solve_challenge(page, kind)`: `kind != "text"` → прежний `RuntimeError(f"SmartCaptcha: {kind} challenge is not supported yet")`;
     `"text"` → ДОСЛОВНО `return await self._solve_text(page)`.
   - ДОСЛОВНО `async def _solve_text(self, page) -> Optional[str]` и константа ДОСЛОВНО `MAX_TEXT_ROUNDS = 3`;
     цикл ДОСЛОВНО `        for round_no in range(MAX_TEXT_ROUNDS):`. Раунд:
     1. в advanced-iframe дождаться видимой `.AdvancedCaptcha-View img` с загруженной картинкой
        (`naturalWidth > 0`, `complete`), а со второго раунда — ещё и с `src`, отличным от `src` прошлого раунда
        (виджет может обновить картинку с задержкой); запомнить `src`; скриншот элемента → `bytes`;
     2. `text = await _bounded(self.vision_classifier.read_text(shot))`. LLM выключен (`self.vision_classifier.enabled`
        ложно или `read_text` поднял `RuntimeError` с `disabled`) → сразу
        `RuntimeError("SmartCaptcha: text challenge needs the vision LLM")`, submit не нажимать. Любая другая ошибка
        классификатора (`ValueError`, иной `RuntimeError`, таймаут отдельного вызова) — раунд засчитан как
        неудачный: нажать кнопку обновления `button[data-testid="refresh"]`, если видна, и перейти к следующему
        раунду (он ждёт новый `src`);
     3. ответ ДОСЛОВНО `answer = " ".join(text.lower().split())`; очистить `input[name="rep"]`, набрать
        `press_sequentially(answer, delay=...)` (небольшая задержка между клавишами), нажать
        `button[data-testid="submit"]`;
     4. перед нажатием submit запомнить состояние подсказки `.Textinput-Hint` (видима ли и её текст); ждать до
        10 с исход: непустой `input[name="smart-token"]` на основной странице → вернуть токен; `src` картинки
        сменился ИЛИ подсказка стала видимой/сменила текст ОТНОСИТЕЛЬНО запомненного состояния → неверно,
        следующий раунд (подсказка, оставшаяся от прошлого отказа, отказом текущего раунда не считается);
        advanced-iframe скрылся без токена → вернуть `None` (опрос `_poll` продолжит и прочтёт токен);
        ничего → следующий раунд.
     Раунды кончились → `RuntimeError("SmartCaptcha: text challenge not solved in 3 rounds")`.
   - В `_poll` возвращённый `_solve_challenge` токен (не `None`) — сразу результат задачи.
   - Все обращения к странице в `_solve_text` — через `_bounded` (дедлайн опроса). В логах — номер раунда и длина
     ответа, не сам ответ.
4. **Тесты — `tests/test_m4b_unit.py`** (без сети, Chromium из образа, поддельный Яндекс через `page.route` на
   `https://smartcaptcha.yandexcloud.net/**` по образцу `tests/test_m4a_unit.py`; задание показывается сразу после
   клика; картинка `load-captchaimg?n=<k>` — PNG, собранный в тесте; поддельный iframe сравнивает `rep` с ожидаемым
   ответом раунда; верно → токен в `smart-token` и iframe скрывается; неверно → новая картинка `n=k+1` и видимая
   `.Textinput-Hint`. Классификатор — заглушка с записью вызовов). Имена:
   - `test_T1_first_round`: заглушка отвечает верно (ответ содержит уникальное слово-маркер) → `solve` возвращает
     токен, `read_text` вызван 1 раз, байты — PNG-скриншот (`\x89PNG`); в захваченных stdout И stderr (`capfd`) за
     весь `solve` нет ни маркера, ни ответа;
   - `test_T2_retry`: первый ответ неверный, второй верный → токен; `read_text` вызван 2 раза, на разных картинках
     (байты различаются); submit нажат 2 раза; поддельный iframe после первого отказа ОСТАВЛЯЕТ подсказку видимой
     с тем же текстом, а на второй (верный) ответ отвечает токеном не сразу, а через 1,5 с — солвер не должен
     засчитать второй раунд отказом из-за старой подсказки;
   - `test_T3_exhausted`: всегда неверно → `RuntimeError` с `not solved in 3 rounds`, `read_text` вызван ровно 3 раза;
   - `test_T4_normalize`: заглушка отдаёт `"  ПРИВЕТ   Мир "`, поддельный iframe ждёт `привет мир` → токен;
   - `test_T5_llm_disabled`: заглушка поднимает `RuntimeError("Vision LLM is disabled (no API key)")` →
     `RuntimeError` с `needs the vision LLM`, submit не нажат;
   - `test_T5b_llm_glitch`: первый вызов заглушки поднимает `ValueError("vision LLM returned no text")`, второй
     отвечает верно → токен; refresh нажат, `read_text` вызван 2 раза на разных картинках;
   - `test_T5c_no_setup`: солвер без вызова `setup()` (`vision_classifier is None`), `VisionLLMClassifier`
     подменён в модуле солвера заглушкой → текстовое задание решается, классификатор создан лениво;
   - `test_T6_silhouette_unchanged`: задание `_silhouette` → прежняя ошибка `silhouette challenge is not supported yet`;
   - `test_T7_read_text`: `read_text` с подменённым `_call_qwen_cli` — `'{"text": " Парус  "}'` → `"Парус"`;
     `'{}'`, `'{"text": ""}'`, `'{"text": 5}'` → `ValueError`; в stdout и stderr (`capfd`) нет слова `Парус`;
     временный файл удалён;
   - `test_T7b_schema_on_cli`: `asyncio.create_subprocess_exec` подменён фейком, который записывает argv и отдаёт
     JSON-вывод CLI с `structured_result` → для `read_text` файл из аргумента `--json-schema @<путь>` прочитан
     В МОМЕНТ вызова и содержит свойство `text` (и не `indices`); для `classify_tiles` — свойство `indices`;
     остальные флаги песочницы (`--approval-mode plan`, `--max-tool-calls 0`, `--core-tools structured_output`)
     в argv обоих вызовов;
   - `test_T8_deadline`: `DEADLINE_SECONDS` подменён на 6, заглушка `read_text` отмечает момент вызова и спит 30 с →
     `read_text` БЫЛ вызван; `solve` поднимает `RuntimeError`, текст которого содержит `no token within 6s`, за
     время от 6 до 12 с от старта опроса; вызов заглушки отменён (её `CancelledError` зафиксирован).
   Существующие тесты M4a (`tests/test_m4a_unit.py`, `tests/test_m4a_gaps.py`), если какой-то из них ломается от
   нового `DEADLINE_SECONDS` или от того, что текстовое задание больше не ошибка «not supported», — поправить
   минимально, не ослабляя проверку; каждое изменение — в отчёт.
5. **Документация.** README — строка `yandex_smartcaptcha`: текстовое задание решается через vision LLM (нужен
   ключ), точность зависит от сложности ключа, с датацентрового IP Яндекс верные ответы не принимает — нужен
   резидентный `proxy`; силуэты не решаются. `CHANGELOG.md` — в `## [Unreleased]`.

## Не трогать

- Всё, кроме: `workers/solvers/smartcaptcha.py`, `workers/classifiers/vision_llm.py` (только п. 1),
  `tests/test_m4b_unit.py` (новый), `tests/test_m4a_unit.py` и `tests/test_m4a_gaps.py` (только см. п. 4), `README.md`,
  `CHANGELOG.md`, эта спека. `probes/` — не править, не коммитить.
- Прокси, браузер, воркер, другие солверы, схемы API — не менять. Образ не пересобирать, `docker system prune` и
  удаление образов запрещены. Живой Яндекс и живой LLM в тестах не дёргать.

## Разрешения

- Docker под своим пользователем без сети. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный без сети.** Команда: `python3 probes/m4b_check.py green .`
- **AC-002 — предписанный код на месте.** Команда: `python3 probes/m4b_check.py code .`
- **AC-003 — мутанты убиты.** Команда: `python3 probes/m4b_check.py mutants .`
- **AC-004 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m4b_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m4b-check/`, удаляется сам). Перед отчётом прогони все четыре команды сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно четыре записи AC-001…AC-004:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Скриншот картинки в поддельном iframe не получается, параметр схемы ломает `classify_tiles` или существующие тесты,
либо раунды не укладываются в дедлайн без изменения файлов вне списка — не обходи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

После M4b — живой стенд постановщика (резидентный прокси, ключи с простыми заданиями) и релиз 1.3.0.
