# M2b — task_id без переиспользования и безопасный init_db

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-10
- **BASE_SHA:** `bffe9bb9e54aa2983b53be4e4add659f6f397487` — конец вехи M2 («Document task_id reuse after retention purge»)
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m2b-task-ids` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — коммитами поверх BASE.
- Тесты — в уже собранном образе `anticaptcha:m2-accept` (не пересобирать: зависимости вехой не меняются),
  код монтируется read-only, база — во временном каталоге:
  `docker run --rm --network none -e ANTICAPTCHA_DATABASE_PATH=/tmp/m2b/anticaptcha.db -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m2-accept sh -c 'mkdir -p /tmp/m2b && python -m pytest -q -p no:cacheprovider -rf <узлы>'`
- Постановщик кладёт untracked: эту спеку `docs/specs/m2b-task-ids.md` (закоммитить с работой, не править) и
  пробник `probes/m2b_task_id_probe.py` (sha256 `2db308fa8af135d8f578d02c2a2188ab4e0114ddefab3f8f2ea9fffa26a4f0ed`,
  7166 байт) и чекер критериев `probes/m2b_check.py` — оба НЕ коммитить, НЕ править, НЕ удалять.

## Задача и почему

1. **Переиспользование `task_id`.** `tasks.id` — SQLite `INTEGER PRIMARY KEY` без `AUTOINCREMENT`: когда
   чистка M2 удаляет строку с максимальным id, следующая задача получает этот id снова, и клиент со старым id
   видит чужую (свою же новую) задачу вместо 404. Владелец решил чинить в 1.1.0.
   ⚠️ `Column(..., autoincrement=True)` в SQLAlchemy 2.0.23 для SQLite AUTOINCREMENT **не даёт** (замерено
   исполнителем M2): нужен табличный параметр `__table_args__ = {"sqlite_autoincrement": True}`. На живых базах
   (в проде уже есть база 1.0.x) таблицу надо пересоздать — `ALTER TABLE` AUTOINCREMENT не добавляет.
2. **Гонка `init_db()`.** API и воркер вызывают `init_db()` при старте; на свежем томе они стартуют одновременно,
   и `create_all` второго процесса падает `table users already exists` (воспроизведено пробником). Создание
   таблиц и миграцию надо сериализовать одной транзакцией `BEGIN IMMEDIATE`.

## Что проверено вживую, а что предположение

Проверено постановщиком 10.11 в образе `anticaptcha:m2-accept` на BASE:
- DDL `tasks` на BASE: `id INTEGER NOT NULL, …, PRIMARY KEY (id), FOREIGN KEY(api_key_id) REFERENCES api_keys (id)`
  плюс индекс `ix_tasks_id`; на `tasks.id` не ссылается ни одна таблица (`grep ForeignKey app/models`).
- Пробник на BASE: 5 из 5 сценариев красные по задуманной причине (нет AUTOINCREMENT; гонка `table users already exists`).
- Эталонная реализация постановщика по схеме ниже даёт пробник 5/5 зелёным три прогона подряд и полный сьют
  зелёным (193 passed); мутации «нет `__table_args__`», «нет вызова миграции», «нет `BEGIN IMMEDIATE`»,
  «старая таблица не удалена» пробник убивает.
- `init_db()` (`app/database.py`) сейчас: `import app.models` и `Base.metadata.create_all(bind=engine)`;
  вызывается из `app/main.py`, `workers/task_worker.py` (`run()`), `init_db.py`.

## Что сделать

1. `app/models/task.py`: в класс `Task` сразу после `__tablename__ = "tasks"` строку ДОСЛОВНО
   (по ней работает чекер):

   ```python
       __table_args__ = {"sqlite_autoincrement": True}
   ```

2. `app/database.py`: `init_db()` делает всё в ОДНОЙ транзакции на одном соединении:

   ```python
       with engine.connect() as conn:
           conn.exec_driver_sql("BEGIN IMMEDIATE")
           Base.metadata.create_all(bind=conn)
           _migrate_tasks_autoincrement(conn)
           conn.commit()
   ```

   Строки `        conn.exec_driver_sql("BEGIN IMMEDIATE")` и `        _migrate_tasks_autoincrement(conn)` — ДОСЛОВНО,
   каждая ровно один раз в файле (отступ 8 пробелов). Остальное — на твоё усмотрение, если поведение то же.

3. `_migrate_tasks_autoincrement(conn) -> bool` (модульная функция в `app/database.py`, docstring — зачем):
   - читает DDL `tasks` из `sqlite_master`; нет таблицы или в DDL уже есть `AUTOINCREMENT` → `False`, ничего не делает;
   - иначе: переименовать `tasks` во временное имя; удалить индексы, оставшиеся на временной таблице (у них
     прежние имена, иначе создание новой таблицы упадёт на `ix_tasks_id`); `Task.__table__.create(conn)`;
     перелить строки `INSERT INTO tasks (<все колонки модели>) SELECT <те же> FROM <временная>`; удалить
     временную таблицу; `True`. После переливки `sqlite_sequence` сам получает максимум id — следующая задача
     идёт с `max(id) + 1` даже после удаления всех строк.
   - Колонки берутся из модели (`Task.__table__.columns`), не хардкодом.

4. `tests/test_task_ids.py` — новый файл. Сценарии пробника как pytest-тесты (каждый — в своём подпроцессе со своим
   `ANTICAPTCHA_DATABASE_PATH`, движок строится при импорте `app.database`): свежая база не переиспользует id после
   удаления всех строк; легаси-база (таблица без AUTOINCREMENT с id 1, 2, 5 и индексом) мигрируется, строки и
   индекс сохранены, временной таблицы не осталось, после удаления всех строк новый id = 6; повторный `init_db()`
   ничего не ломает; `purge_tasks` + новая задача не переиспользуют id; два процесса одновременно делают
   `init_db()` на легаси-базе — оба rc=0, миграция ровно одна, данные целы. Легаси-таблицу удобно строить так же,
   как пробник: `Task.__table__.to_metadata(md)` и `dialect_options["sqlite"]["autoincrement"] = False`.

5. Документация: в `docs/specs/limits.md` и `CHANGELOG.md` убрать запись про ограничение «task_id reuse» (обе
   языковые версии из коммита BASE) и вместо неё записать исправление: `sqlite_autoincrement=True`, миграция
   существующей таблицы при `init_db()`, сериализация `init_db()` через `BEGIN IMMEDIATE`. Слово
   `sqlite_autoincrement` в `CHANGELOG.md` обязательно. Исправь и формулировку «`autoincrement=True` у `Task.id`»
   везде, где она осталась (`docs/specs/limits.md`, `CHANGELOG.md`): она неверна, см. «Задача», п. 1.

## Не трогать

- Всё, кроме: `app/models/task.py`, `app/database.py`, `tests/test_task_ids.py`, `CHANGELOG.md`,
  `docs/specs/limits.md`, эта спека.
- `probes/` — не править, не коммитить. Образ не пересобирать; `docker system prune` и удаление образов запрещены.
- `app/api/tasks.py`, `workers/**`, чарт, зависимости — без изменений.

## Разрешения

- Docker без сети под своим пользователем. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — полный сьют зелёный.** Команда: `python3 probes/m2b_check.py green .`
- **AC-002 — пробник постановщика зелёный и не тронут.** Команда: `python3 probes/m2b_check.py probe .`
- **AC-003 — тесты вехи убивают три мутации.** Команда: `python3 probes/m2b_check.py mutants .`
- **AC-004 — ограничение снято из документации, исправление записано.** Команда: `python3 probes/m2b_check.py docs .`
- **AC-005 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 probes/m2b_check.py scope .`

Мутации AC-003: убрать строку `__table_args__`; заменить вызов `_migrate_tasks_autoincrement(conn)` на `pass`;
заменить `BEGIN IMMEDIATE` на `pass` (гонка — до трёх прогонов, убит при любом падении). Чекер работает в свежей
копии HEAD (`tmp/m2b-check/`, удаляется сам). Перед отчётом прогони все пять команд сам.

## Авторевью

Не требуется: правка мала; ревью и независимые мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно пять записей AC-001…AC-005:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Пробник красный по причине, которую нельзя устранить в разрешённых файлах, или существующий тест ломается от
сериализации `init_db()` — не обходи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

После приёмки постановщик вливает M2 + M2b в `main`, бампает `appVersion` до 1.1.0 и выпускает релиз.
