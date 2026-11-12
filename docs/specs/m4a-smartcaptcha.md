# M4a — Yandex SmartCaptcha: тип задачи, прокси, механика виджета

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-12
- **BASE_SHA:** `f8d38fd7019ba23bcc72302f7232c3dbbc89ccf4` — релиз 1.2.1
- **Исполнитель:** `cx`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m4a-smartcaptcha` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only. Юнит-тесты — без сети:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m4a/a.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m4a && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
  E2E — то же без `--network none` и с `-e ANTICAPTCHA_E2E=1`.
- Постановщик кладёт untracked чекер `probes/m4a_check.py` (НЕ коммитить, НЕ править, НЕ удалять). Эту спеку —
  `docs/specs/m4a-smartcaptcha.md` — закоммитить с работой.

## Задача и почему

Сервис не умеет Yandex SmartCaptcha: API принимает пять типов (`app/schemas/task.py`), воркер знает пять солверов
(`workers/task_worker.py`, `SOLVERS`). `workers/solvers/yandex.py` — мёртвый код: зарегистрирован только в
неиспользуемом `workers/solvers/unified.py`, возвращает bool вместо токена, селекторы выдуманы, при отсутствии
задания «решает» сном. Веха добавляет тип `yandex_smartcaptcha` с механикой виджета и возвратом токена, необязательное
поле `proxy` (Яндекс с датацентровых адресов всегда выдаёт задание и не принимает ответы — см. ниже), и удаляет
мёртвый код. Решение самих заданий (текст, силуэты) — следующая веха M4b; здесь задание распознаётся и задача падает
с понятной ошибкой.

## Что проверено вживую, а что предположение

Проверено постановщиком 12.11 (Chromium из образа, playwright-stealth, датацентровый IP, 11 живых сайтов + официальная
демка `https://captcha-api.yandex.ru/demo`, ключ `FEXfAbHQsToo97VidNVk3j4dC74nGW1DgdxjtNB9`):

- Скрипт `https://smartcaptcha.yandexcloud.net/captcha.js`; контейнер `div.smart-captcha[data-sitekey]`; после
  рендера внутри контейнера (`[data-testid="smartCaptcha-container"]`) — `iframe[data-testid="checkbox-iframe"]`,
  скрытый `iframe[data-testid="backend-iframe"]`, при задании — `iframe[data-testid="advanced-iframe"]`.
- Чекбокс: в checkbox-iframe кнопка `#js-button` (`role=checkbox`). Слайдер (основное задание у части ключей): в том
  же iframe `.SliderCaptcha`, ползунок `[data-testid="thumb"]` (`role=slider`), протянуть вправо до конца дорожки.
- Задание: в advanced-iframe корень `.AdvancedCaptcha`; модификатор `.AdvancedCaptcha_image` — текст (картинка +
  `input[name="rep"]`), `.AdvancedCaptcha_silhouette` — силуэты. Кнопка `button[data-testid="submit"]`.
- Токен: `input[name="smart-token"]` (hidden) внутри контейнера на основной странице; JS API
  `window.smartCaptcha.getResponse()`; невидимый режим — `window.smartCaptcha.execute()`.
- Проверка домена у ключей включена — `render_mode="widget"` (подмена первой навигации, как в M3a) обязателен для
  чужих страниц; с подменой виджет рендерится на всех 11 ключах.
- 45 из 45 попыток с датацентрового IP закончились заданием; даже верные ответы, введённые руками, Яндекс не принял
  («Дополнительная проверка» по кругу). Отсюда поле `proxy`.
- Тестовых ключей «всегда проходит» у Яндекса нет. Токен содержит IP решавшего (по документации).
- Chromium в Playwright не поддерживает авторизацию для SOCKS5-прокси.

Предположение: поведение `getResponse()` до рендера и точная разметка невидимого режима — поэтому механика тестируется
на поддельном DOM, повторяющем селекторы выше, а живой Яндекс — только в e2e.

## Что сделать

1. **API.** `TaskType.YANDEX_SMARTCAPTCHA = "yandex_smartcaptcha"` в `app/schemas/task.py`.
2. **Прокси — новый модуль `workers/solvers/proxy.py`:** `def parse_proxy(value) -> Optional[dict]`.
   - `None` (ключа нет или null) → `None`. Не строка → `ValueError`.
   - Формат `scheme://[user:pass@]host:port`; схемы `http`, `https`, `socks5` (иначе `ValueError`); порт обязателен
     (1–65535); логин без пароля или пароль без логина → `ValueError`; `socks5` с логином → `ValueError` с текстом
     `socks5 proxy with credentials is not supported`.
   - Хост прокси обязан быть публичным. `_blocked_ip` из `workers/solvers/url_guard.py` принимает объект
     `ipaddress.IPv4Address`/`IPv6Address`, не строку: IP-литерал → `ipaddress.ip_address(host)`; имя → резолв
     `socket.getaddrinfo(name, port, proto=socket.IPPROTO_TCP)`, КАЖДЫЙ адрес (зону `%…` отрезать) →
     `ipaddress.ip_address` → `_blocked_ip`; хоть один заблокирован, резолв пуст или упал → `ValueError`;
     `localhost`/`*.localhost` — отказ до резолва. Иначе прокси = SSRF.
   - Возвращает словарь для Playwright: `{"server": "<scheme>://<ip>:<port>"}` + `"username"`/`"password"`, если
     заданы (логин и пароль — URL-декодированные). В `server` — ПРОВЕРЕННЫЙ IP-адрес (первый из отсортированных
     адресов резолва, IPv6 в скобках), а не имя: иначе Chromium резолвит имя заново и DNS rebinding уводит прокси на
     внутренний адрес. Учётные данные НИКОГДА не попадают в текст исключений и логи.
   - Функция синхронная (резолв DNS) — из async-кода её зовут только через `asyncio.to_thread`.
3. **Браузер — `app/utils/browser.py`:** `new_page(self, stealth: bool = True, proxy: Optional[dict] = None)`. С
   `proxy` — отдельный контекст `await browser.new_context(proxy=proxy)` и страница в нём; новый метод
   `async def close_page(self, page)` закрывает страницу и, если контекст создан под неё, контекст (без прокси —
   только страницу, как сейчас). Принадлежность контекста менеджер хранит сам (например, словарь
   `id(page) -> context`, запись снимается в `close_page`), а не угадывает по `page.context`: у страницы из
   `browser.new_page()` тоже есть контекст, его закрывает `page.close()`. Поведение без `proxy` не меняется.
4. **Виджет.** В `_WIDGETS` (`workers/solvers/widget_page.py`) — запись `"yandex_smartcaptcha"`: скрипт
   `https://smartcaptcha.yandexcloud.net/captcha.js`, контейнер `<div class="smart-captcha" data-sitekey="{site_key}"></div>`.
5. **Солвер — новый файл `workers/solvers/smartcaptcha.py`, класс `SmartCaptchaSolver(BaseSolver)`**, `BaseSolver` —
   из `app.utils.captcha_solver` (НЕ из `workers.solvers.base`, там другой класс с другим `solve`; интерфейс как
   у `TurnstileSolver`: `setup`/`cleanup`/`async def solve(self, input_data) -> dict`):
   - вход `check_browser_input`, затем `validate_page_url` (в потоке, как у Turnstile), затем `parse_proxy(input_data.get("proxy"))` —
     (через `asyncio.to_thread`, как `validate_page_url`) — всё до запуска браузера; `page = await browser_manager.new_page(stealth=True, proxy=proxy)`, в `finally` —
     `await browser_manager.close_page(page)`;
   - `render_mode="widget"` → `install_widget_page(page, page_url, "yandex_smartcaptcha", site_key)`;
   - константа ДОСЛОВНО `DEADLINE_SECONDS = 60`; опрос ДОСЛОВНО `async def _poll(self, page) -> str` до дедлайна,
     каждый `page.evaluate`/вызов локатора ограничен `asyncio.wait_for` остатком дедлайна (минимум 0,5 с, как в
     Turnstile). Шаг опроса по порядку:
     1. токен — ДОСЛОВНО `async def _read_token(self, page) -> Optional[str]`: непустое значение
        `input[name="smart-token"]` на основной странице → вернуть его;
     2. задание — ДОСЛОВНО `async def _challenge_kind(self, page) -> Optional[str]`: видимый
        `iframe[data-testid="advanced-iframe"]`, внутри `.AdvancedCaptcha` → `"text"` (`_image`), `"silhouette"`
        (`_silhouette`), иначе `"unknown"`; задание есть → ДОСЛОВНО `await self._solve_challenge(page, kind)`, в M4a
        этот метод поднимает `RuntimeError(f"SmartCaptcha: {kind} challenge is not supported yet")`;
     3. слайдер (`.SliderCaptcha [data-testid="thumb"]` в checkbox-iframe) — протянуть мышью от центра ползунка до
        правого края `.SliderCaptcha` за несколько шагов;
     4. чекбокс (`#js-button` в checkbox-iframe) — клик;
     5. checkbox-iframe нет уже ≥ 3 с с момента загрузки страницы, а `window.smartCaptcha` есть —
        `window.smartCaptcha.execute()` один раз (невидимая). Раньше 3 с — не вызывать: виджет ещё рендерится.
     **Повтор действия (шаги 3–4).** Вживую (ресерч M4a, демка Яндекса) кнопка `#js-button` становится видимой
     раньше, чем виджет готов: клик через 0,8 с после загрузки молча теряется, клик через 5 с вызывает задание.
     Поэтому протяжка/клик — не «один раз», а: после действия ждать до 5 с появления токена или
     advanced-iframe; ничего не появилось — повторить действие; не больше ДОСЛОВНО `MAX_ACTIONS = 4` действий
     (протяжки и клики вместе) за задачу.
     Дедлайн → `RuntimeError("SmartCaptcha: no token within 60s")`.
   - результат `{"token": <строка>}`; в логах — только длина токена.
   - ДОСЛОВНО и ровно по одному разу в `smartcaptcha.py`: строки-селекторы `'input[name="smart-token"]'`,
     `'#js-button'` и вызов `smartCaptcha.execute()` (по ним чекер ставит мутантов); в `app/utils/browser.py` — ровно
     один `new_context(proxy=proxy)`; в `proxy.py` проверка хоста — вызовами `_blocked_ip(`.
6. **Воркер.** `"yandex_smartcaptcha": SmartCaptchaSolver` в `SOLVERS`. В `process_task`: после того как задача стала
   `solved` или `failed`, из сохранённого `task.input_data` удалить ключ `proxy` (учётные данные клиента не лежат в
   БД дольше задачи) — функция ДОСЛОВНО `def _strip_proxy(raw: str) -> str:` (строка
   определения целиком, с двоеточием, на уровне модуля) (JSON-строка в JSON-строку; невалидный
   JSON или не-объект — вернуть как есть). То же — в `recover_interrupted_tasks` (задачи, переведённые в `failed`
   после рестарта воркера).
7. **Мёртвый код.** Удалить `workers/solvers/yandex.py`; из `workers/solvers/unified.py` — импорт и регистрацию
   Yandex-солверов и их упоминание в списке поддерживаемых. В `tests/test_solvers.py` — `test_import_yandex` переписать
   на импорт `SmartCaptchaSolver` из нового модуля, а из `test_all_solvers_registered` (и любых других тестов этого
   файла, требующих удаляемые регистрации) убрать ожидание Yandex-солверов. Прочие файлы корня репо (`test_*.py` вне `tests/`) не трогать.
8. **Тесты.**
   - `tests/test_m4a_unit.py` (без сети, Chromium из образа; каждый тест — свой `asyncio.run` с закрытием браузера
     в `finally`). Поддельный Яндекс — `page.route` на `https://smartcaptcha.yandexcloud.net/**`: свой `captcha.js`
     создаёт в `.smart-captcha` контейнер `[data-testid="smartCaptcha-container"]` с `iframe[data-testid="checkbox-iframe"]`
     (src на тот же хост, отдаётся маршрутом), `input[name="smart-token"]` и `window.smartCaptcha` (`execute`,
     `getResponse`); iframe сообщает родителю о клике/протяжке через `postMessage`. Сценарии — параметр в URL скрипта
     или в `page_url`. Имена:
     - `test_Y1_checkbox`: клик по `#js-button` → токен в `smart-token` → `solve` (render_mode `widget`, page_url
       `https://example.com/`) возвращает этот токен; без клика токен не появляется; поддельный виджет ИГНОРИРУЕТ
       клики в первые 1,5 с после загрузки (кнопка при этом уже видна) — солвер обязан повторить клик;
     - `test_Y1b_dead_widget`: виджет игнорирует все клики → `DEADLINE_SECONDS` подменён на 30, кликов ровно
       `MAX_ACTIONS` (счётчик в поддельном iframe), затем `RuntimeError` с `no token`;
     - `test_Y2_slider`: токен появляется, только если ползунок протянут не меньше чем на 90 % дорожки;
     - `test_Y3_invisible`: чекбокса нет, токен — только после вызова `execute()`; `execute()` вызван один раз и не
       раньше чем через 3 с после загрузки; отдельный сценарий — checkbox-iframe появляется через 1 с после загрузки:
       `execute()` не вызывается вовсе, токен — по клику;
     - `test_Y4_text_challenge`: после клика появляется advanced-iframe с `.AdvancedCaptcha_image` → `RuntimeError`,
       в тексте `text challenge`;
     - `test_Y5_silhouette_challenge`: то же с `.AdvancedCaptcha_silhouette` → в тексте `silhouette challenge`;
     - `test_Y6_parse_proxy`: таблица — `http://u:p%40ss@8.8.8.8:8080` → `server == "http://8.8.8.8:8080"`,
       `username="u"`, `password="p@ss"`; без порта; схема `ftp`; `socks5://u:p@8.8.8.8:1080` (текст ошибки — про credentials);
       `http://10.0.0.1:3128`, `http://127.0.0.1:3128`, `http://localhost:3128`; логин без пароля; не строка;
       `None` → `None`. Ни в одном тексте исключения нет пароля;
     - `test_Y7_proxy_context`: заглушка браузера (monkeypatch `get_browser`) записывает аргументы `new_context` →
       `new_page(proxy=...)` передал словарь прокси, `close_page` закрыл и страницу, и контекст; без прокси
       `new_context` не вызывается;
     - `test_Y8_strip_proxy`: `process_task` на временной SQLite с заглушкой солвера — и для `solved`, и для
       `failed` в сохранённом `input_data` нет `proxy`, остальные поля на месте; то же для задачи в `processing`
       после `recover_interrupted_tasks`; `_strip_proxy` на невалидном JSON возвращает вход как есть;
     - `test_Y10_hung_page`: `DEADLINE_SECONDS` подменён на 3 (monkeypatch), поддельная страница через 0,5 с после
       загрузки вешает главный поток (`while (true) {}`) → `solve` поднимает `RuntimeError` с `no token` не позже чем
       через 10 с от старта (каждый `evaluate`/локатор в опросе ограничен остатком дедлайна);
     - `test_Y6b_proxy_pins_ip`: `parse_proxy("http://u:p@proxy.example:3128")` с подменённым `socket.getaddrinfo`
       (имя → `8.8.4.4`) даёт `server == "http://8.8.4.4:3128"`; резолв в `10.1.2.3` → `ValueError`;
     - `test_Y9_api_type`: `POST /api/v1/task` с `type: "yandex_smartcaptcha"` принимается (как устроены
       существующие тесты в `tests/test_api.py`).
   - `tests/test_m4a_e2e.py` (skip без `ANTICAPTCHA_E2E=1`): `test_E8_yandex_demo` — ключ демки выше,
     `page_url="https://captcha-api.yandex.ru/demo"`, `render_mode="widget"` → либо токен (≥ 50 символов), либо
     `RuntimeError` с `challenge is not supported yet` (с датацентра ожидается второе); таймаут/иная ошибка — провал.
9. **Документация.** README — тип `yandex_smartcaptcha`, поле `proxy` (формат, схемы, SOCKS5 без логина, хост должен
   быть публичным, удаляется из БД после задачи), ограничение: с датацентрового IP Яндекс выдаёт задание всегда, токен
   привязан к IP решавшего, задания пока не решаются (M4b). `CHANGELOG.md` — `## [Unreleased]`, отдельной строкой:
   удалён нерабочий `yandex.py` (прежняя запись о «full implementation» была неверной).

## Не трогать

- Всё, кроме: `app/schemas/task.py`, `app/utils/browser.py`, `workers/task_worker.py`, `workers/solvers/widget_page.py`,
  `workers/solvers/smartcaptcha.py` (новый), `workers/solvers/proxy.py` (новый), `workers/solvers/yandex.py`
  (удаление), `workers/solvers/unified.py`, `tests/test_solvers.py`, `tests/test_m4a_unit.py`, `tests/test_m4a_e2e.py`,
  `README.md`, `CHANGELOG.md`, эта спека. `probes/` — не править, не коммитить.
- Другие солверы, классификаторы, `url_guard.py` (только импорт `_blocked_ip`), схемы ответов API, чарт — не менять.
- Образ не пересобирать; `docker system prune` и удаление образов запрещены. Живой Яндекс — только в `test_E8`.

## Разрешения

- Docker под своим пользователем; сеть — только для e2e. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный без сети.** Команда: `python3 probes/m4a_check.py green .`
- **AC-002 — предписанный код на месте.** Команда: `python3 probes/m4a_check.py code .`
- **AC-003 — e2e на демке Яндекса зелёный.** Команда: `python3 probes/m4a_check.py e2e .`
- **AC-004 — мутанты убиты.** Команда: `python3 probes/m4a_check.py mutants .`
- **AC-005 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m4a_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m4a-check/`, удаляется сам). Перед отчётом прогони все пять команд сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно пять записей AC-001…AC-005:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Поддельный Яндекс в `page.route` без сети не поднимается, отдельный контекст с прокси ломает stealth или
существующие тесты, либо e2e на демке даёт ни токен, ни распознанное задание — не обходи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

M4b — решение заданий «текст» и «силуэты» через vision LLM в `_solve_challenge`. Затем живой стенд с резидентным
прокси и релиз 1.3.0 постановщиком.
