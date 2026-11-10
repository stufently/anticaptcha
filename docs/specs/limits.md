# Limits and Constraints

**Last updated:** 2026-11-10

## System Limits

### Throughput
- **Maximum tasks/hour:** 100
- **Concurrent tasks:** 1 (single worker)
- **Worker poll interval:** 1 second

### Resources
- **Minimum RAM:** 8 GB
- **Recommended RAM:** 16 GB
- **Minimum CPU:** 4 cores
- **GPU:** Optional (4GB+ VRAM recommended)
- **Disk space:** 5-10 GB (models + dependencies)

## Technical Constraints

### Browser (Playwright)
- **Timeout:** 30 seconds default
- **Headless mode:** Yes (no GUI)
- **Browser:** Chromium 158.0.8127.18 (Chrome for Testing), Playwright 1.65.0
- **Browser sandbox:** OFF — `--no-sandbox`, `--disable-setuid-sandbox` and
  `--no-zygote` in `app/utils/browser.py`. Forced by the runtime environment,
  not a preference (all points measured in Docker on this host, uid 1000,
  default seccomp, no privileges):
  - the default docker seccomp profile blocks the unprivileged user namespaces
    the sandbox needs → `FATAL ... No usable sandbox!`;
  - the SUID `chrome_sandbox` helper needs root → `Zygote process exited
    prematurely with exit code 82`, and `not running as root` under
    `no-new-privileges`;
  - with the sandbox enabled `--no-zygote` is rejected outright → `Zygote cannot
    be disabled if sandbox is enabled`;
  - only `seccompProfile: Unconfined` or `CAP_SYS_ADMIN` would change that, and
    the chart grants neither. Playwright also passes `--no-sandbox` itself while
    `chromium_sandbox=False` (its default), so the flag only restates reality.

  Consequence: a renderer exploit on a client-controlled page runs as uid 1000
  inside the worker. The available mitigation is keeping Chromium current, which
  is why the pin moved 1.40.0 (Chromium 120, November 2023) → 1.65.0.

### Database (SQLite)
- **File:** data/anticaptcha.db
- **Max size:** limited by disk; the retention cleanup below keeps it bounded
- **Concurrent writes:** Single writer (SQLite limitation)
- **Journal:** WAL with `busy_timeout=5000` and `auto_vacuum=INCREMENTAL`; the
  auto_vacuum pragma must run BEFORE `journal_mode=WAL`, otherwise a new
  database is created with `auto_vacuum=0`

### API
- **Rate limit:** none per request; there is a quota on active tasks per key
- **Active tasks per API key:** 20 (`ANTICAPTCHA_MAX_ACTIVE_TASKS_PER_KEY`,
  `0` = no limit), counting `pending` and `processing`. Over the limit
  `POST /api/v1/task` returns **429** `Too many active tasks for this API key:
  limit is N`. The count is a single SQL `COUNT` taken under `BEGIN IMMEDIATE`,
  so concurrent creates from one key cannot all pass the check together.
- **Auth:** `Authorization: Bearer <token>` — client API key for `/api/v1/task*`; admin token (`ANTICAPTCHA_ADMIN_TOKEN`) or an admin user's API key for `/api/v1/user` and `/api/v1/api-key/*`
- **Registration:** closed — users are created only by an admin (HTTP API or `python -m app.cli create-user`)
- **Max retries:** 3

### Task retention and cleanup (`workers/cleanup.py`)
- **Input data:** `input_data` (up to 5 MB of base64 per task) is set to `""` on
  `solved`/`failed` tasks older than **1 h**
  (`ANTICAPTCHA_INPUT_RETENTION_HOURS`). The row itself, `result` and
  `error_message` stay, and `GET /api/v1/task/{id}` keeps working — it never
  reads `input_data`. A client cannot produce `""`: the API stores
  `json.dumps(dict)`, so at least `"{}"`.
- **Task rows:** `solved`/`failed` tasks older than **7 days**
  (`ANTICAPTCHA_TASK_RETENTION_DAYS`) are deleted. `pending`/`processing` are
  never touched whatever their age, and the `stats` table is never touched.
- **Age comparison is strict** (`created_at < now - retention`); `now` is naive
  UTC, the same clock the worker writes into `created_at`.
- **Order and batching:** deletes first, then input clearing; at most 100 rows
  per statement, every batch with its own commit (no long write transaction).
  `batch_size` must be `>= 1` — `purge_tasks` raises `ValueError` otherwise,
  because SQLite reads `LIMIT 0` as "no rows" (the round would report a clean
  database while trimming nothing) and `LIMIT -1` as "no limit at all" (the whole
  backlog in the one long transaction the batching avoids).
- **Space reclaim:** a database still on `auto_vacuum != 2` is migrated once by a
  full `VACUUM`, which needs free space for a copy of the live data (measured:
  4.8 s and a `-wal` grown to 1083 MB for 1 GB of live data on NVMe) — so it runs
  only after the purge, and only when the volume can hold the copy (see "One-time
  `auto_vacuum` migration" below). An already INCREMENTAL database is trimmed with
  `incremental_vacuum` until the freelist is empty, then
  `wal_checkpoint(TRUNCATE)` shrinks `-wal`; a full `VACUUM` is never repeated.
- **Schedule:** the worker calls `run_cleanup()` every **600 s**
  (`ANTICAPTCHA_CLEANUP_INTERVAL_SECONDS`), the first round right after recovery
  of interrupted tasks, in a separate thread (`asyncio.to_thread`): a synchronous
  `VACUUM` on the event loop would stop the heartbeat and the liveness probe
  would kill the pod in the middle of it. A failed round is logged, not raised,
  and still starts the next interval.
- **Task ids are never reused:** `tasks` is created with `__table_args__ =
  {"sqlite_autoincrement": True}`, so SQLite keeps the highest id ever used in
  `sqlite_sequence` and hands out the id after it. A purge that deletes the row
  with the highest id no longer gives that id back, and a client that kept an old
  id gets a 404 instead of its own NEW task. `autoincrement=True` on the `Task.id`
  column does **not** emit AUTOINCREMENT on SQLite (measured on SQLAlchemy
  2.0.23) — only the table argument does.
- **Existing databases are migrated by `init_db()`:** SQLite cannot add
  AUTOINCREMENT with `ALTER TABLE`, so `_migrate_tasks_autoincrement()`
  (`app/database.py`) rebuilds a `tasks` table whose DDL in `sqlite_master` has no
  AUTOINCREMENT — rename it, drop the indexes that moved with it (they keep their
  names, `ix_tasks_id` among them), create the table from the model, copy the rows
  back (which seeds `sqlite_sequence` with `max(id)`), drop the temporary table.
  The column list comes from `Task.__table__.columns`. With no table, or with a
  DDL that already has AUTOINCREMENT, it returns `False` and touches nothing, so a
  repeated `init_db()` changes nothing.
- **`init_db()` is serialized:** the API and the worker both call it at startup
  and on a fresh volume they start at the same moment. Table creation and the
  migration run in ONE `BEGIN IMMEDIATE` transaction on one connection; without
  the writer lock the second `create_all` died on `table users already exists`
  (reproduced). Now the loser waits out the lock (`busy_timeout` 5 s) and sees the
  tables the winner committed.
- **`init_db()` retries the lock:** `busy_timeout` bounds ONE attempt, and a
  migration in the other process can outlast it - the loser then died on
  `database is locked` and the API or the worker did not start (reproduced:
  5.06 s). `init_db(lock_wait_seconds=60.0)` therefore repeats `_init_db_once()`
  every 0.5 s while the error contains `locked` and the budget is not up; any
  other `OperationalError` (a damaged file, a read-only volume) is raised at once.
- The chart sets none of these values — the code defaults above apply.

#### One-time `auto_vacuum` migration: the full `VACUUM`
A database created before `auto_vacuum=INCREMENTAL` was set on connect is
migrated once, by `reclaim_space()` in `workers/cleanup.py`. That one-time
`VACUUM` carries two limits of its own:

- **It holds the write lock for the whole rebuild.** SQLite copies every live
  page into a temporary database and then replaces the file, so the `VACUUM` is
  one exclusive operation - `AUTOCOMMIT` on the SQLAlchemy side only means no
  transaction is wrapped around it. While it runs, another process that wants to
  write waits `busy_timeout` and then fails: `POST /api/v1/task` takes
  `BEGIN IMMEDIATE` to count the quota and ends with `database is locked`
  (measured 5.01 s against a held write lock), i.e. an HTTP 500, and the worker
  cannot commit either. On a small database this is a fraction of a second;
  measured on NVMe for 1 GB of live data: 4.8 s. It happens once per database, at
  the first cleanup round after the upgrade.
- **It needs free space for a second copy of the database.**
  `_has_room_for_vacuum()` compares `shutil.disk_usage(<database directory>).free`
  with `2 * <database file size>` and, when the volume is too small, skips the
  migration with `⚠️ Not enough free space for the auto_vacuum migration VACUUM;
  skipped`. Everything else in the round still runs - `wal_checkpoint(TRUNCATE)`
  included - the database keeps working on `auto_vacuum=0`, and the next cleanup
  round tries again. Without the check the `VACUUM` would fail halfway through on
  a full volume and be attempted again every cycle, each time taking the write
  lock while it copies.

### Settings bounds
`max_active_tasks_per_key >= 0`, `cleanup_interval_seconds >= 1`,
`input_retention_hours >= 0` and `task_retention_days >= 0` are enforced by
pydantic (`Field(..., ge=...)` in `app/config.py`), so an out-of-bounds value -
from the environment or from `.env` - fails at startup instead of being used.
A negative quota would silently switch the limit off (`create_task` only checks
`if limit > 0`), a negative retention would move the purge boundary
`now - retention` into the future and delete freshly created tasks, and a zero
`cleanup_interval_seconds` would run the cleanup on every poll. The bounds are
inclusive: `max_active_tasks_per_key=0` still means "no limit".

### Client images (`image_text`)
- **Request body:** 5 MiB (`ANTICAPTCHA_MAX_BODY_BYTES`) — 413 before parsing
- **Max pixels:** 4 000 000 (`ANTICAPTCHA_MAX_IMAGE_PIXELS`)
- **Max side:** 4096 px (`ANTICAPTCHA_MAX_IMAGE_SIDE`)
- Checked from the header only (`PIL.Image.open` without `load()`) before
  `cv2.imdecode`, in `workers/solvers/image_text.py::check_image_dimensions`;
  equality passes, only a larger value is rejected
- Over limit → task `failed` with `Image too large: …`; unreadable header →
  `Unsupported or corrupt image: …`. Nothing is decoded in either case
- Why: a flat-colour 20000×20000 PNG is ~1.2 MB on the wire (it fits the body
  limit) but ~4.1 GB to decode and preprocess — enough for the OOM killer to
  take out a 4 GiB worker

### Worker liveness (heartbeat)
- **File:** `/tmp/worker-heartbeat` (`ANTICAPTCHA_WORKER_HEARTBEAT_FILE`,
  `worker.heartbeatFile` in the chart)
- **Interval:** 10 s (`ANTICAPTCHA_WORKER_HEARTBEAT_INTERVAL`), written from
  the worker's event loop after `setup_solvers()` and cancelled when `run()`
  exits; the write is atomic (temp file + `os.replace`)
- **Probe:** `python -m workers.heartbeat --check --max-age N` → rc 0 fresh,
  1 stale/missing/non-numeric
- **Chart:** `startupProbe` 10 s × 60 (600 s budget for model loading) and
  `livenessProbe` 30 s × 3 with `maxAgeSeconds: 300`, both removed by
  `worker.livenessProbe.enabled: false`
- `maxAgeSeconds` must stay above `ANTICAPTCHA_TASK_TIMEOUT` (120 s), otherwise
  a long solve looks like a dead worker

### ML Models
- **Yolo:** yolov8n-cls.pt (6 MB)
- **EasyOCR:** Auto-downloaded (~100 MB)

## CAPTCHA Limitations

### reCAPTCHA v2/v3
- Image challenges require Yolo model
- May not work on heavily protected sites
- Browser fingerprint detection possible

### hCaptcha
- Similar to reCAPTCHA
- Requires trained Yolo model for images

### Image-to-text
- OCR accuracy: 70-95% (depends on distortion)
- Works best on simple CAPTCHAs
- Complex distortion may fail

### Turnstile
- Usually solves automatically
- May fail on strict sites
- No ML model needed typically

## Scaling Limits

Current architecture is designed for **single user, local use**. For scaling:

1. **Queue system:** Add Redis/RabbitMQ for multiple workers
2. **Database:** Switch to PostgreSQL for concurrent access
3. **Workers:** Run multiple worker instances
4. **GPU:** Add GPU for faster ML inference

## Security Limits

- API keys stored as SHA-256 hashes
- Passwords hashed with salted SHA-256
- No HTTPS (local network only)
- No per-request rate limiting (trusted local user); the only throttle is the
  per-key active-task quota → 429, see "API" above
- No browser sandbox: Chromium runs with `--no-sandbox` because the container
  runtime forbids it, see "Browser (Playwright)" above
- No runtime package installation: `YOLO_AUTOINSTALL=false`, so ultralytics
  cannot `pip install pi-heif` (or anything else) from inside a running worker