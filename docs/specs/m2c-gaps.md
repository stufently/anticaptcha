# M2c — дыры в тестах M2, границы настроек, место под VACUUM, повтор init_db

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-10
- **BASE_SHA:** `6ef26772881725b1939c34a41926284dd3252314` — конец вехи M2b
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m2c-gaps` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в уже собранном образе `anticaptcha:m2-accept` (не пересобирать), код монтируется read-only:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m2c/anticaptcha.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m2c && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
- Постановщик кладёт untracked в `probes/` (НЕ коммитить, НЕ править, НЕ удалять): чекер `probes/m2c_check.py`,
  патчи выживших мутантов `probes/m2c-mutants/*.patch` (10 штук), исполняемые тексты тестов
  `probes/m2c-suggested_tests.py`. Эту спеку — `docs/specs/m2c-gaps.md` — закоммитить с работой.

## Задача и почему

Независимый мутационный прогон (Codex) по тестам M2 дал 27 мутаций, 10 выжили: Q06 (отказ по квоте делает
`commit` вместо `rollback`), C07/C08 (явный `batch_size` игнорируется), C09/C10 (явный ноль срока хранения
подменяется значением по умолчанию), W03–W07 (планировщик чистки: первый вызов сразу при любом `monotonic`,
монотонные часы, без повтора после сбоя до интервала, интервал из настроек, вызов действительно в цикле).
Найдены и дефекты кода:

- `workers/cleanup.py` `purge_tasks`: `batch_size` не проверяется — при 0 чистка молча ничего не делает, при −1
  SQLite `LIMIT -1` снимает ограничение и удаляет всё одной транзакцией.
- `app/config.py`: числовые настройки не ограничены снизу — отрицательная квота отключает лимит, отрицательные сроки
  хранения сдвигают границу чистки в будущее и удаляют свежие задачи.

Ревью Codex по M2: разовая миграция `VACUUM` (`reclaim_space`) не проверяет свободное место — на маленьком томе
она упадёт и будет повторяться каждый цикл; и держит блокировку записи всё время перестройки (POST к API ждут
`busy_timeout` 5 с и дальше получают ошибку) — это документируем.

Ревью Codex по M2b: `init_db()` ждёт чужую `BEGIN IMMEDIATE` не дольше `busy_timeout` (5 с) и при долгой миграции
второго процесса падает `database is locked` без повтора (воспроизведено за 5,06 с) — запуск API или воркера
прерывается.

## Что проверено вживую, а что предположение

Проверено постановщиком 10.11 на коде M2 (`bffe9bb`): каждый тест из `probes/m2c-suggested_tests.py` Codex прогнал на
HEAD (зелёный) и на своём мутанте (красный); патчи выживших лежат в `probes/m2c-mutants/`. M2b менял только
`app/models/task.py`, `app/database.py`, тесты и документацию — места, куда бьют эти патчи, им не задеты.

## Что сделать

1. **`tests/test_m2_gaps.py`** — новый файл: тесты из `probes/m2c-suggested_tests.py` (можно как есть; помощники
   они грузят из `tests/test_quota.py` и `tests/test_cleanup.py`). В тексте файла должны встречаться id
   `Q06, C07, C08, C09, C10, W03, W04, W05, W06, W07` (имена тестов или `ids=`), плюс тесты ниже с `F1`, `B1`, `V1`, `L1` в именах.

2. **Границы настроек** — `app/config.py`: `from pydantic import Field`, и четыре строки ДОСЛОВНО (по ним работает чекер):

   ```python
       max_active_tasks_per_key: int = Field(20, ge=0)
       cleanup_interval_seconds: int = Field(600, ge=1)
       input_retention_hours: float = Field(1, ge=0)
       task_retention_days: float = Field(7, ge=0)
   ```

   Тест(ы) `test_F1_*`: `Settings(<поле>=<ниже границы>)` → `pydantic.ValidationError` для каждого из четырёх
   полей; граничные значения (0, 1, 0, 0 соответственно) принимаются.

3. **`batch_size`** — `workers/cleanup.py` `purge_tasks`, первой проверкой ДОСЛОВНО:

   ```python
       if batch_size < 1:
           raise ValueError(f"batch_size must be >= 1, got {batch_size}")
   ```

   Тест `test_B1_*`: 0 и −1 → `ValueError`, ни одна строка не тронута; 1 работает.

4. **Место под VACUUM** — `workers/cleanup.py`: модульная функция (сигнатура ДОСЛОВНО):

   ```python
   def _has_room_for_vacuum(engine) -> bool:
   ```

   Путь берётся из `engine.url.database`; пустой путь или `:memory:` → `True`; иначе размер файла базы (0, если
   файла нет) и `shutil.disk_usage(<каталог базы>).free`; последняя строка функции ДОСЛОВНО
   `    return free >= 2 * size`. В `reclaim_space` ветку миграции переписать так (две строки — ДОСЛОВНО):

   ```python
           if auto_vacuum != 2 and not _has_room_for_vacuum(engine):
               print("⚠️ Not enough free space for the auto_vacuum migration VACUUM; skipped", flush=True)
           elif auto_vacuum != 2:
               conn.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
               conn.exec_driver_sql("VACUUM")
           else:
               ...  # incremental_vacuum как сейчас
   ```

   `wal_checkpoint(TRUNCATE)` после ветвления остаётся во всех трёх случаях. Тесты `test_V1_*`: легаси-база
   (auto_vacuum=0) при подменённом `shutil.disk_usage` с `free` меньше двух размеров — VACUUM не выполнен
   (`PRAGMA auto_vacuum` остался 0), предупреждение напечатано, исключения нет; при достаточном месте — миграция
   прошла (auto_vacuum=2); граница: `free == 2 * size` — миграция идёт.

5. **Повтор `init_db`** — `app/database.py`: текущее тело `init_db()` вынести в `_init_db_once()` без изменений, а
   `init_db` сделать повторяющей обёрткой. Сигнатура и строка проверки ДОСЛОВНО:

   ```python
   def init_db(lock_wait_seconds: float = 60.0):
       ...
       deadline = time.monotonic() + lock_wait_seconds
       while True:
           try:
               _init_db_once()
               return
           except OperationalError as exc:
               if "locked" not in str(exc) or time.monotonic() >= deadline:
                   raise
               time.sleep(0.5)
   ```

   (`OperationalError` — из `sqlalchemy.exc`; `import time`). Вызовы `init_db()` в `app/main.py`, воркере и
   `init_db.py` не трогать. Тесты `test_L1_*` (в подпроцессах со своим `ANTICAPTCHA_DATABASE_PATH`): другой процесс
   держит `BEGIN IMMEDIATE` ~6 с — `init_db()` дожидается и проходит; с `lock_wait_seconds=0` — падает
   `OperationalError`; ошибка без слова `locked` (например, подменённый `_init_db_once`, бросающий
   `OperationalError("disk I/O error")`) — пробрасывается сразу, без повторов.

6. **Документация** — `docs/specs/limits.md`: раздел про разовую миграцию: VACUUM на старой базе держит блокировку
   записи на всё время перестройки (POST к API в это время ждут `busy_timeout` и могут получить ошибку; на
   маленькой базе это доли секунды), требует свободного места на два размера базы — `_has_room_for_vacuum`
   проверяет это и при нехватке пропускает миграцию с предупреждением (следующий цикл попробует снова).
   Слова `VACUUM` и `_has_room_for_vacuum` обязательны. `CHANGELOG.md` — короткая запись.

## Не трогать

- Всё, кроме: `app/config.py`, `app/database.py`, `workers/cleanup.py`, `tests/test_m2_gaps.py`, `CHANGELOG.md`,
  `docs/specs/limits.md`, эта спека. `probes/` — не править, не коммитить.
- Образ не пересобирать; `docker system prune` и удаление образов запрещены.

## Разрешения

- Docker без сети под своим пользователем. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный.** Команда: `python3 probes/m2c_check.py green .`
- **AC-002 — предписанный код и тесты на месте.** Команда: `python3 probes/m2c_check.py code .`
- **AC-003 — 18 мутантов (10 выживших M2 + 8 новых) убиты.** Команда: `python3 probes/m2c_check.py mutants .`
- **AC-004 — изменены только разрешённые файлы, всё закоммичено, VACUUM описан.** Команда: `python3 probes/m2c_check.py scope .`

Чекер работает в свежей копии HEAD (`tmp/m2c-check/`, удаляется сам). Перед отчётом прогони все четыре команды сам.

## Авторевью

Не требуется: ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно четыре записи AC-001…AC-004:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Патч выжившего мутанта не ложится на код BASE, или предписанный код ломает существующий тест — не обходи и не
правь патчи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

После приёмки постановщик вливает M2 + M2b + M2c в `main`, бампает `appVersion` до 1.1.0 и выпускает релиз.
