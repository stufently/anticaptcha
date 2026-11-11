# M2d — остановка qwen CLI целиком и мёртвый код браузера

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-11
- **BASE_SHA:** `1ab247790b2794aa7113e69245936c9fbd9d4a29` — релиз 1.1.0
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m2d-cleanup` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в уже собранном образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m2d/anticaptcha.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m2d && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
- Постановщик кладёт untracked чекер `probes/m2d_check.py` (НЕ коммитить, НЕ править, НЕ удалять). Эту спеку —
  `docs/specs/m2d-cleanup.md` — закоммитить с работой.

## Задача и почему

1. `workers/classifiers/vision_llm.py` `_reap`: `os.killpg` вызывается, только пока `process.returncode is None`.
   Сценарий: qwen CLI (лидер группы, `start_new_session=True`) завершился, а его потомок унаследовал stdout/stderr и
   живёт. `communicate()` ждёт закрытия труб до таймаута 90 с, к этому моменту asyncio уже собрал лидера
   (`returncode` выставлен), `killpg` пропускается — потомок остаётся жить. Это записано в Known limitations 1.1.0.
   Почему `killpg` по номеру лидера безопасен и после его сборки: Linux не выдаёт номер PID новому процессу, пока
   этот номер служит PGID/SID хоть одному живому процессу. Пока в группе есть потомок, номер принадлежит нашей
   группе; группа пуста — `killpg` даёт `ProcessLookupError`.
2. Мёртвый код с устаревшим User-Agent `Chrome/120`: `BrowserManager.new_context` (`app/utils/browser.py`) и
   `create_stealth_page` (`app/utils/stealth.py`) нигде не вызываются (проверено grep по `app`, `workers`, `tests`).

## Что проверено вживую, а что предположение

- Проверено постановщиком 11.11 чтением BASE: тело `_reap` (строки 59–77 `vision_llm.py`) — `killpg` под условием
  `process.returncode is None`; вызов CLI — `create_subprocess_exec(..., start_new_session=True)`; `new_context` и
  `create_stealth_page` — единственные места с `Chrome/120`, вызовов нет (grep `app`, `workers`, `tests`).
- Предположение (его проверяет AC-003, прогоняя новый тест на коде BASE): asyncio выставляет `returncode` при выходе
  лидера, не дожидаясь закрытия труб, которые держит потомок.

## Что сделать

1. **`_reap`** — условие перед `os.killpg` ДОСЛОВНО (по нему работает чекер), строка встречается в файле один раз:

   ```python
       if isinstance(pid, int) and pid > 0:
   ```

   Комментарий над ним переписать: почему номер группы нельзя переиспользовать, пока в ней есть живой процесс
   (абзац выше). Остальное в `_reap` не менять.

2. **Тест** `tests/test_m2d_reap.py` (имена тестов с `R1`): настоящий подпроцесс через
   `asyncio.create_subprocess_exec("sh", "-c", "sleep 300 & echo $! > <tmp>/gc.pid; exit 0", stdout=PIPE,
   stderr=PIPE, start_new_session=True)`; дождаться, пока лидер собран (`process.returncode is not None`, опрос с
   ограничением ~5 с — `communicate()` при этом не ждать, трубы держит `sleep`); вызвать `_reap(process)`; проверить,
   что процесс из `gc.pid` умер в пределах ~5 с (`os.kill(pid, 0)` → `ProcessLookupError`, учесть зомби: проверять
   через `/proc/<pid>/stat` состояние `Z` или его отсутствие). Тест обязан падать на коде BASE. В `finally` —
   добить `gc.pid` по PID, если жив. Второй тест `R1`: `_reap` на уже пустой группе (лидер и потомок мертвы) не
   бросает исключений.

3. **Мёртвый код:** удалить метод `BrowserManager.new_context` и функцию `create_stealth_page` целиком; ставшие
   ненужными импорты (`BrowserContext` и т. п.) убрать, если больше не используются. Строки `Chrome/120` в `app/` и
   `workers/` не должно остаться.

4. **`CHANGELOG.md`:** раздел `## [Unreleased]` сверху: Fixed — `_reap` убивает группу и после сборки лидера;
   Removed — мёртвый код с UA Chrome/120. Из Known limitations раздела 1.1.0 текст не удалять (это история релиза).

## Не трогать

- Всё, кроме: `workers/classifiers/vision_llm.py`, `app/utils/browser.py`, `app/utils/stealth.py`,
  `tests/test_m2d_reap.py`, `CHANGELOG.md`, эта спека, а в `tests/test_m1_gaps.py` — только тест, который закрепляет
  старое поведение («killpg must not target a PID that was already reaped»): переписать под новое (на собранном
  лидере `killpg` вызывается с его PID). `probes/` — не править, не коммитить.
- Образ не пересобирать; `docker system prune` и удаление образов запрещены.

## Разрешения

- Docker без сети под своим пользователем. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный.** Команда: `python3 probes/m2d_check.py green .`
- **AC-002 — предписанный код на месте, мёртвого кода нет.** Команда: `python3 probes/m2d_check.py code .`
- **AC-003 — мутанты убиты (условие returncode, удалённый killpg).** Команда: `python3 probes/m2d_check.py mutants .`
- **AC-004 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m2d_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m2d-check/`, удаляется сам). Перед отчётом прогони все четыре команды сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно четыре записи AC-001…AC-004:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Тест R1 не удаётся сделать красным на коде BASE или стабильным на новом коде (гонка, зависимость от окружения
контейнера) — не обходи (не ослабляй проверку, не мокай `os.killpg`): `fail` с объяснением и стоп.

## Стыки с соседними вехами

Следом идёт M3 (браузерные солверы) от HEAD этой вехи.
