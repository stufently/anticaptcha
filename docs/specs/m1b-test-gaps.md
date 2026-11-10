# M1b — дыры в тестах M1, дефекты heartbeat/qwen и находки ревью Codex

- **Репозиторий:** `anticaptcha` (публичный)
- **Дата:** 2026-11-10
- **BASE_SHA:** `d9ae88afc767c0cc921b8978b640046ba0019b4a` — конец вехи M1 (ветка `m1-hardening`)
- **Исполнитель:** `qw`

## Где работать

- Одноразовый клон от BASE, рабочая ветка `m1b-test-gaps` (путь — в указателе запуска). Живое дерево не трогать.
- git pull не делать, push запрещён; `git add` по именам. Работа — ОДНИМ или несколькими коммитами поверх BASE.
- Тесты — в уже собранном образе `anticaptcha:m1` (не пересобирать), исходники монтируются read-only:
  `docker run --rm --network none -e COLUMNS=1000 -v "$PWD/tests:/app/tests:ro" -v "$PWD/app:/app/app:ro" -v "$PWD/workers:/app/workers:ro" -v "$PWD/config:/app/config:ro" -v "$PWD/chart:/app/chart:ro" anticaptcha:m1 python -m pytest -q -p no:cacheprovider -rf <узлы>`
- Постановщик кладёт untracked: эту спеку `docs/specs/m1b-test-gaps.md` (закоммитить с работой, не править).
  Чекер лежит вне клона, путь — в командах критериев.

## Задача и почему

Независимый мутационный прогон (Codex) по тестам M1 дал 28 мутаций, 11 выжили — новые тесты не ловят
эти поломки. Кроме того найдены два дефекта боевого кода:

- **D1** `workers/heartbeat.py` `is_fresh`: метка `inf` или метка из будущего считается свежей навсегда
  (`now - stamp <= max_age` верно для любого `stamp >= now - max_age`). Liveness-проба тогда никогда не
  перезапустит зависший воркер.
- **D2** `workers/classifiers/vision_llm.py`: при отмене корутины (`CancelledError` во время
  `process.communicate()`) дочерний процесс qwen не убивается, а на таймауте после `kill()` его не ждут
  (`wait()`), остаётся зомби.

Ревью Codex по M1 (10.11) нашло ещё четыре места:

- **J1** `workers/solvers/image_text.py` `check_image_dimensions`: JPEG 2000 с двумя блоками `ihdr` —
  Pillow берёт последний (32×32), OpenJPEG в `cv2.imdecode` первый (2500×2000); 505-байтный файл проходит
  лимит и раздувается при декодировании. Лечится белым списком форматов, которые Pillow и OpenCV читают
  одинаково: PNG, JPEG, WEBP, BMP.
- **R** `workers/task_worker.py`: ошибка восстановления прерванных задач на старте глотается навсегда —
  задачи `processing` висят до следующего рестарта. Нужен повтор на каждой итерации цикла до успеха.
- **B** `app/utils/browser.py` `get_browser`: два одновременных вызова могут оба запускать Chromium, и
  неудачный запуск останавливает общий драйвер, убивая браузер соседа. Нужна `asyncio.Lock`.
- **S** `chart/templates/deployment.yaml`: фильтр `ANTICAPTCHA_ADMIN_TOKEN` действует только на `env`; при
  пустом `worker.existingSecret` воркер получает общий Secret целиком через `envFrom`, с токеном. Код чарта
  не меняем — документируем в `chart/README.md` и комментарием у `worker.existingSecret` в `chart/values.yaml`.

## Что проверено вживую, а что предположение

Проверено постановщиком 10.11 на BASE: 22 теста M1 зелёные; каждый тест из списка ниже Codex прогнал
на HEAD (зелёный) и на своём мутанте (красный, предметный assert). Тексты тестов — ниже, их можно
брать как есть. Предположение: `FakeProcess` в `tests/test_vision_llm_sandbox.py` метода `wait()` не
имеет — его нужно добавить (async, отмечает факт ожидания), иначе код D2 упадёт на фейке.

## Что сделать

1. **D1** — в `workers/heartbeat.py` добавить `import math`, а хвост `is_fresh` после чтения `stamp`
   заменить ДОСЛОВНО на (отступ 4 пробела, текст должен совпасть байт в байт — по нему работает чекер):

   ```python
       if not math.isfinite(stamp):
           return False
       if now is None:
           now = time.time()
       age = now - stamp
       return -max_age <= age <= max_age
   ```

   Смысл: метка ровно на границе `max_age` свежая; будущая — свежая только в пределах `max_age`
   (допуск на расхождение часов), дальше — протухшая. Обнови docstring.

2. **D2** — в `classify_tiles` (место `await asyncio.wait_for(process.communicate(), timeout=90.0)`)
   обработчики привести ДОСЛОВНО к виду (отступы как в файле: `except` — 12 пробелов):

   ```python
               except asyncio.TimeoutError:
                   print(f"❌ qwen process timed out after 90 seconds")
                   process.kill()
                   await process.wait()
                   raise RuntimeError("Vision LLM classification timed out")
               except asyncio.CancelledError:
                   process.kill()
                   await process.wait()
                   raise
   ```

   `CancelledError` в Python 3.11 — `BaseException`, внешний `except Exception` его не перехватит; так и надо.
   Строку `timeout=90.0` не менять.

3. **`FakeProcess`** в `tests/test_vision_llm_sandbox.py`: добавить `async def wait(self)`, ставящий
   `self.waited = True` (в `__init__` — `self.waited = False`). Существующие тесты не ломать.

4. **`tests/test_m1_gaps.py`** — новый файл. Имена тестов обязаны начинаться с `test_<ID>_`:
   `C03, C04, C06, C10, C13, C14, C15, C16, C18, C26, C27` — тексты ниже; плюс `J1`, `R1`, `B1` (пункты 5–7) и свои:
   - `test_D1_rejects_nonfinite_and_far_future` — `inf`, `nan` и `10000` при `now=100, max_age=30` → `False`;
     `120` при `now=100, max_age=30` → `True` (будущее в пределах допуска);
   - `test_D2_cancel_kills_and_waits_child` — отмена во время `communicate` → `CancelledError`
     наружу, `child.killed and child.waited`, временного `captcha_*.png` не осталось;
   - `test_D2_timeout_kills_and_waits_child` — `communicate` бросает `asyncio.TimeoutError` →
     `RuntimeError`, `child.killed and child.waited`.

   ⚠️ Тест C13 ниже написан под старый `is_fresh`; с новым кодом он должен остаться зелёным (метка 50,
   now 100: возраст 50 ≤ 60 свежая, > 40 протухшая) — проверь. C14 зовёт `is_fresh(path, 30, now=100.0)`
   с меткой 70 — возраст ровно 30, должно быть `True`.

5. **J1** — в `workers/solvers/image_text.py` на уровне модуля (после импортов) ДОСЛОВНО:

   ```python
   ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "BMP"})
   ```

   в `check_image_dimensions` внутри `with` рядом с `width, height = header.size` запомнить
   `fmt = header.format`, а сразу ПОСЛЕ блока `try/except` (до чтения лимитов) ДОСЛОВНО:

   ```python
       if fmt not in ALLOWED_IMAGE_FORMATS:
           raise ValueError(f"Unsupported image format: {fmt}")
   ```

   Тест `test_J1_rejects_jpeg2000_and_tiff`: JP2 (`Image.new("RGB", (8, 8)).save(buf, format="JPEG2000")` —
   в образе работает) и TIFF → `ValueError` с `Unsupported image format`; PNG, JPEG, WEBP, BMP 8×8 проходят.

6. **R** — в `workers/task_worker.py`: в `__init__` `self._recovery_pending = True`; метод ДОСЛОВНО
   (отступ метода 4 пробела):

   ```python
       def _try_recover(self) -> None:
           """Requeue interrupted tasks; on failure keep the flag set to retry later."""
           try:
               self.recover_interrupted_tasks()
           except Exception as exc:
               print(
                   f"⚠️ Recovery of interrupted tasks failed: {type(exc).__name__}: {exc}",
                   flush=True,
               )
               return
           self._recovery_pending = False
   ```

   В `run()` блок `try: self.recover_interrupted_tasks() except ...` после `init_db()` заменить вызовом
   `self._try_recover()`; в цикле `while self.running:` первой строкой внутри `try:` (перед выборкой
   задачи; отступ 16 пробелов) ДОСЛОВНО:

   ```python
                   if self._recovery_pending:
                       self._try_recover()
   ```

   Тест `test_R1_recovery_retried_until_success`: первый вызов `recover_interrupted_tasks` бросает
   `sqlite3.OperationalError("database is locked")`, второй успешен; после нескольких итераций цикла
   вызовов ровно 2 (не больше — успех снимает флаг). Каркас — как у `test_C10` (фейковые `SessionLocal`,
   `setup_solvers`, малый `worker_poll_interval`).

7. **B** — в `app/utils/browser.py`: в `BrowserManager.__init__` ДОСЛОВНО `        self._lock = asyncio.Lock()`
   (импортировать `asyncio`, если нет); тело `get_browser` целиком обернуть в
   `        async with self._lock:` (эта строка дословно, тело — на уровень глубже).
   Тест `test_B1_concurrent_get_browser_launches_once`: фейковый `launch`, который делает
   `await asyncio.sleep(0)` перед возвратом; `asyncio.gather` двух `get_browser()` → `launch` вызван один
   раз, оба получили один и тот же объект. Фейк — через `install_fake` из `tests/test_browser_reconnect.py`
   (при необходимости — свой в `test_m1_gaps.py`).

8. **S** — `chart/README.md`: абзац про `worker.existingSecret`: если общий Secret (`existingSecret`) содержит
   `ANTICAPTCHA_ADMIN_TOKEN`, задай воркеру отдельный Secret без него, иначе токен попадёт в воркер через
   `envFrom` (фильтр действует только на список `env`). Слова `worker.existingSecret` и `envFrom` в абзаце
   обязательны. Тот же смысл одной строкой комментария у `worker.existingSecret` в `chart/values.yaml`.

9. В `CHANGELOG.md` — короткая запись (раздел Unreleased/1.1.0, как принято в файле).

### Тексты тестов от Codex (проверены на HEAD и мутантах)

Общий заголовок файла:

```python
import asyncio
import contextlib
import math
import os
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, "/app/tests")
from test_image_limits import png_header
from test_browser_reconnect import install_fake
from test_vision_llm_sandbox import FakeProcess, install_fake_exec, make_classifier
from workers.solvers.image_text import check_image_dimensions
from workers import heartbeat, task_worker
from app.utils.browser import BrowserManager
```

```python
def test_C03_vertical_side_limit():
    with pytest.raises(ValueError, match="Image too large:"):
        check_image_dimensions(png_header(10, 4097))


def test_C04_default_pixel_limit_rejects_five_million():
    with pytest.raises(ValueError, match="Image too large:"):
        check_image_dimensions(png_header(2500, 2000))


def test_C06_default_pixel_limit_accepts_four_million():
    try:
        dimensions = check_image_dimensions(png_header(2000, 2000))
    except ValueError as exc:
        pytest.fail(f"default pixel limit must accept 4 million pixels: {exc}")
    assert dimensions == (2000, 2000)


def test_C10_heartbeat_cancelled_before_run_returns(monkeypatch):
    async def no_setup(self):
        pass

    class EmptyDB:
        def query(self, *args):
            return self
        def filter(self, *args):
            return self
        def order_by(self, *args):
            return self
        def first(self):
            return None
        def close(self):
            pass

    monkeypatch.setattr(task_worker, "init_db", lambda: None)
    monkeypatch.setattr(task_worker.TaskWorker, "recover_interrupted_tasks", lambda self: 0)
    monkeypatch.setattr(task_worker.TaskWorker, "setup_solvers", no_setup)
    monkeypatch.setattr(task_worker.TaskWorker, "cleanup_solvers", no_setup)
    monkeypatch.setattr(task_worker, "SessionLocal", EmptyDB)
    monkeypatch.setattr(task_worker.settings, "worker_poll_interval", 0.01)

    async def scenario():
        started = asyncio.Event()
        beats = []

        async def fake_loop(path, interval):
            beats.append(asyncio.current_task())
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(task_worker, "heartbeat_loop", fake_loop)
        worker = task_worker.TaskWorker()
        runner = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            worker.stop()
            await asyncio.wait_for(runner, timeout=2)
            assert len(beats) == 1
            assert beats[0].done() and beats[0].cancelled()
        finally:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
            for beat in beats:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat

    asyncio.run(scenario())


def test_C13_cli_respects_custom_max_age(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat"
    path.write_text("50", encoding="ascii")
    monkeypatch.setattr(heartbeat.time, "time", lambda: 100.0)
    assert heartbeat.main(["--check", "--max-age", "60", "--path", str(path)]) == 0
    assert heartbeat.main(["--check", "--max-age", "40", "--path", str(path)]) == 1


def test_C14_exact_max_age_is_fresh(tmp_path):
    path = tmp_path / "heartbeat"
    path.write_text("70", encoding="ascii")
    assert heartbeat.is_fresh(str(path), max_age=30, now=100.0) is True


def test_C15_cli_uses_settings_path(monkeypatch):
    calls = []
    monkeypatch.setattr(heartbeat.settings, "worker_heartbeat_file", "/tmp/custom-heartbeat")

    def fake_is_fresh(path, age):
        calls.append((path, age))
        return True

    monkeypatch.setattr(heartbeat, "is_fresh", fake_is_fresh)
    assert heartbeat.main(["--check", "--max-age", "45"]) == 0
    assert calls == [("/tmp/custom-heartbeat", 45.0)]


def test_C16_liveness_command_rejects_stale_stamp(tmp_path):
    text = pathlib.Path("/app/chart/templates/deployment.yaml").read_text()
    worker = text.split('command: ["python", "-m", "workers.task_worker"]', 1)[1]
    block = worker.split("          livenessProbe:\n", 1)[1].split("            periodSeconds:", 1)[0]
    argv = re.findall(r"^                - (.+)$", block, flags=re.M)
    argv = ["300" if token.startswith("{{") else token for token in argv]
    path = tmp_path / "heartbeat"
    path.write_text("0", encoding="ascii")
    proc = subprocess.run(argv, env={**os.environ, "ANTICAPTCHA_WORKER_HEARTBEAT_FILE": str(path)},
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_C18_disconnect_clears_context(monkeypatch):
    install_fake(monkeypatch)
    manager = BrowserManager()

    async def scenario():
        browser = await manager.get_browser()
        manager._context = object()
        browser.fire("disconnected", browser)
        assert manager._context is None

    asyncio.run(scenario())


def test_C26_python_timeout_remains_bounded(monkeypatch):
    classifier = make_classifier(monkeypatch)
    install_fake_exec(monkeypatch, FakeProcess())
    timeouts = []

    async def fake_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    try:
        assert asyncio.run(classifier.classify_tiles(b"image", "bicycles")) == [0, 3]
        assert timeouts == [90.0]
    finally:
        classifier.cleanup()


def test_C27_attached_path_contains_original_image(monkeypatch):
    classifier = make_classifier(monkeypatch)
    attached = []
    payload = b"exact-original-image-bytes"

    async def fake_exec(*cmd, **kwargs):
        prompt = cmd[cmd.index("-m") + 2]
        reference = next(token for token in prompt.split() if token.startswith("@"))
        attached.append(pathlib.Path(reference[1:].rstrip(".")).read_bytes())
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    try:
        assert asyncio.run(classifier.classify_tiles(payload, "bicycles")) == [0, 3]
        assert attached == [payload]
    finally:
        classifier.cleanup()
```

Если тест из этого списка на твоём коде падает НЕ из-за мутации — разберись и поправь сам тест минимально,
сохранив его проверку (в отчёте — что и почему). Ослаблять ассерт ради зелёного запрещено.

## Не трогать

- Всё, кроме: `tests/test_m1_gaps.py`, `tests/test_vision_llm_sandbox.py` (только `FakeProcess`),
  `workers/heartbeat.py`, `workers/classifiers/vision_llm.py`, `workers/solvers/image_text.py`,
  `workers/task_worker.py`, `app/utils/browser.py`, `chart/README.md`, `chart/values.yaml` (только
  комментарий), `CHANGELOG.md`, эта спека.
- `chart/templates/**`, `config/**`, остальные тесты, `appVersion` — без изменений.
- Образ `anticaptcha:m1` не пересобирать; `docker system prune` и удаление образов запрещены.

## Разрешения

- Docker без сети под своим пользователем. Коммиты в клоне. Запись `report.json`.

## Критерии приёмки

- **AC-001 — новые и старые тесты зелёные.** Команда: `python3 <чекер постановщика>/m1b_check.py green <клон>`
- **AC-002 — код D1 и D2 дословно и полный набор тестов на месте.** Команда: `python3 <чекер постановщика>/m1b_check.py code <клон>`
- **AC-003 — все 20 мутантов ложатся и убиваются.** Команда: `python3 <чекер постановщика>/m1b_check.py mutants <клон>`
- **AC-004 — изменены только разрешённые файлы, всё закоммичено.** Команда: `python3 <чекер постановщика>/m1b_check.py scope <клон>`

Чекер сам накладывает мутанты в свежую копию HEAD (`tmp/m1b-check/`, удаляется после). Перед отчётом
прогони все четыре команды сам.

## Авторевью

Не требуется: правка мала, ревью и мутации делает постановщик.

## Контракт отчёта

`report.json` в корне клона, только поле `criteria`, ровно четыре записи AC-001…AC-004:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked", "command": "<команда>", "rc": 0, "note": "…"}]}
```

Глушители кода возврата (`|| true`, `set +e`) и подмена окружения запрещены.

## Контракт на невыполнимое

Мутант AC-003 выживает и закрыть его можно только правкой вне разрешённых файлов, либо дословный код
(D1, D2, J1, R, B) ломает существующий тест — не обходи: `fail` с объяснением и стоп.

## Стыки с соседними вехами

После приёмки постановщик вливает `m1-hardening` + `m1b-test-gaps` в `main`, затем M2 (Playwright 1.65, квоты).
