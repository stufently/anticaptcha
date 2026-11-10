#!/usr/bin/env python3
"""Mutation gate for milestone m2-playwright-quotas (docs/specs/m2-playwright-quotas.md).

Runs INSIDE the acceptance image, from the clone root (AC-006 mounts app/,
workers/ and tests/ read-write):

    python tests/mutation_gate_m2.py [<group> ...]

Groups: quota, cleanup, database, worker. No argument means every group.

For every mutation, strictly in this order:

  1. save the file bytes and their sha256;
  2. run the TARGET test on the clean tree - it must pass, otherwise the
     mutation is INVALID and does not count;
  3. check that the replaced fragment occurs in the file exactly once;
  4. apply the replacement and run the same test node again;
  5. restore the saved bytes in a `finally` block and verify the sha256;
  6. the mutant is KILLED ("убит") only when the clean run passed, pytest
     returned rc 1 on the mutant, and the `FAILED <node> - ...` line of the
     `-rf` summary contains the mutation's `expect` substring - the assertion
     message of the target test itself, never the name of some other crash.
     Anything else is SURVIVED ("выжил"): a hole in the tests.

pytest runs as a subprocess with COLUMNS=1000, because the short summary line
is cut to the terminal width and the default 80 columns would cut away the very
assertion message `expect` has to match. PYTHONDONTWRITEBYTECODE keeps the
mounted tree free of __pycache__, so no run can import stale bytecode of a
mutated module.

Exit code is 0 only when every mutation of the selected groups is killed.

No mutation in this list is equivalent: each one changes behaviour that its
target test observes (a mutant whose observable behaviour cannot change would
have to be excluded here with a written justification - there is none).
"""
import hashlib
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GROUPS = ("quota", "cleanup", "database", "worker")

MUTATIONS = [
    # --- quota: per-key limit in app/api/tasks.py::create_task --------------
    dict(
        id="Q-1",
        group="quota",
        path="app/api/tasks.py",
        old='        db.connection().exec_driver_sql("BEGIN IMMEDIATE")\n',
        new="",
        node="tests/test_quota.py::test_concurrent_creates_admit_only_one",
        expect="concurrent creates must be serialised by the quota lock",
    ),
    dict(
        id="Q-2",
        group="quota",
        path="app/api/tasks.py",
        old='ACTIVE_STATUSES = ("pending", "processing")',
        new='ACTIVE_STATUSES = ("pending",)',
        node="tests/test_quota.py::test_processing_task_occupies_a_slot",
        expect="must still occupy the slot",
    ),
    dict(
        id="Q-3",
        group="quota",
        path="app/api/tasks.py",
        old="        if active >= limit:",
        new="        if active > limit:",
        node="tests/test_quota.py::test_over_limit_rejected_with_429",
        expect="the third active task must be rejected with 429",
    ),
    dict(
        id="Q-4",
        group="quota",
        path="app/api/tasks.py",
        old="    if limit > 0:",
        new="    if True:",
        node="tests/test_quota.py::test_zero_limit_means_unlimited",
        expect="max_active_tasks_per_key=0 must mean no limit",
    ),
    # --- cleanup: purge rules in workers/cleanup.py ------------------------
    dict(
        id="C-1",
        group="cleanup",
        path="workers/cleanup.py",
        old='FINISHED_STATUSES = ("solved", "failed")',
        new='FINISHED_STATUSES = ("solved", "failed", "pending", "processing")',
        node="tests/test_cleanup.py::test_purge_only_touches_finished_tasks",
        expect="only finished tasks may be purged",
    ),
    dict(
        id="C-2",
        group="cleanup",
        path="workers/cleanup.py",
        old="                    Task.created_at < delete_before,",
        new="                    Task.created_at <= delete_before,",
        node="tests/test_cleanup.py::test_delete_age_boundary_is_strict",
        expect="a task exactly at its retention age must survive",
    ),
    dict(
        id="C-3",
        group="cleanup",
        path="workers/cleanup.py",
        old="                    Task.created_at < input_before,",
        new="                    Task.created_at <= input_before,",
        node="tests/test_cleanup.py::test_input_age_boundary_is_strict",
        expect="an input exactly at its retention age must be kept",
    ),
    dict(
        id="C-4",
        group="cleanup",
        path="workers/cleanup.py",
        old="                    Task.created_at < delete_before,\n"
            "                )\n"
            "                .limit(batch_size)\n",
        new="                    Task.created_at < delete_before,\n"
            "                )\n",
        node="tests/test_cleanup.py::test_deletes_run_in_batches",
        expect="every DELETE batch must stay within batch_size",
    ),
    dict(
        id="C-5",
        group="cleanup",
        path="workers/cleanup.py",
        old="                    Task.created_at < input_before,\n"
            '                    Task.input_data != "",\n'
            "                )\n"
            "                .limit(batch_size)\n",
        new="                    Task.created_at < input_before,\n"
            '                    Task.input_data != "",\n'
            "                )\n",
        node="tests/test_cleanup.py::test_input_updates_run_in_batches",
        expect="every UPDATE batch must stay within batch_size",
    ),
    dict(
        id="C-6",
        group="cleanup",
        path="workers/cleanup.py",
        old="            dbapi_connection = conn.connection.dbapi_connection\n"
            '            dbapi_connection.executescript("PRAGMA incremental_vacuum;")\n',
        new='            conn.exec_driver_sql("PRAGMA incremental_vacuum")\n',
        node="tests/test_cleanup.py::test_incremental_reclaim_empties_the_freelist",
        expect="incremental_vacuum must run to completion",
    ),
    dict(
        id="C-7",
        group="cleanup",
        path="workers/cleanup.py",
        old='        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")\n',
        new="        pass\n",
        node="tests/test_cleanup.py::test_reclaim_truncates_the_wal",
        expect="the -wal file must be truncated",
    ),
    # --- database: pragma order on connect --------------------------------
    dict(
        id="D-1",
        group="database",
        path="app/database.py",
        old='    cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")\n'
            '    cursor.execute("PRAGMA journal_mode=WAL")\n',
        new='    cursor.execute("PRAGMA journal_mode=WAL")\n'
            '    cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")\n',
        node="tests/test_cleanup.py::test_fresh_database_is_created_incremental",
        expect="a fresh database must be created with auto_vacuum=INCREMENTAL",
    ),
    # --- worker: cleanup in the polling loop ------------------------------
    dict(
        id="W-1",
        group="worker",
        path="workers/task_worker.py",
        old="        if last is not None and now - last < settings.cleanup_interval_seconds:\n"
            "            return False\n",
        new="        if False:\n"
            "            return False\n",
        node="tests/test_cleanup.py::test_maybe_cleanup_runs_on_interval",
        expect="the first round runs at once, the next ones every cleanup_interval_seconds",
    ),
    dict(
        id="W-2",
        group="worker",
        path="workers/task_worker.py",
        old="            await asyncio.to_thread(run_cleanup)\n",
        new="            run_cleanup()\n",
        node="tests/test_cleanup.py::test_maybe_cleanup_runs_off_the_event_loop",
        expect="run_cleanup must run off the event-loop thread",
    ),
    dict(
        id="W-3",
        group="worker",
        path="workers/task_worker.py",
        old="        try:\n"
            "            # Off the event loop: the migration VACUUM is synchronous and, on the\n"
            "            # loop, would stall the heartbeat until the liveness probe killed the\n"
            "            # pod in the middle of it.\n"
            "            await asyncio.to_thread(run_cleanup)\n"
            "        except Exception as exc:\n"
            "            print(\n"
            '                f"⚠️ Cleanup failed: {type(exc).__name__}: {exc}",\n'
            "                flush=True,\n"
            "            )\n",
        new="        await asyncio.to_thread(run_cleanup)\n",
        node="tests/test_cleanup.py::test_maybe_cleanup_swallows_errors",
        expect="a cleanup failure must stay inside maybe_cleanup",
    ),
    dict(
        id="W-4",
        group="worker",
        path="workers/task_worker.py",
        old="                # Retention cleanup: after recovery (interrupted tasks are failed\n"
            "                # first, so they are visible to it) and before the session below,\n"
            "                # at most once per settings.cleanup_interval_seconds.\n"
            "                await self.maybe_cleanup()\n",
        new="",
        node="tests/test_cleanup.py::test_worker_loop_calls_maybe_cleanup",
        expect="must await maybe_cleanup() inside its polling loop",
    ),
]


def run_target(node):
    """Run one test node in a subprocess; return (rc, combined output)."""
    env = dict(os.environ)
    env["COLUMNS"] = "1000"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", node],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def failed_line(output, node):
    """The `FAILED <node> - ...` line of the short summary, if there is one."""
    for line in output.splitlines():
        if line.startswith("FAILED ") and node in line:
            return line.strip()
    return None


def last_line(output):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "<no output>"


def apply_mutation(mut):
    """Apply one mutation, measure, restore. Returns (verdict, detail, sha256)."""
    path = REPO_ROOT / mut["path"]
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    print(
        f"\n--- {mut['id']} [{mut['group']}] {mut['path']} sha256={digest}"
        f"\n    target: {mut['node']}\n    expect: {mut['expect']}",
        flush=True,
    )

    verdict, detail = "INVALID", ""
    try:
        # (2) the target test must be green on the clean tree
        rc_clean, out_clean = run_target(mut["node"])
        if rc_clean != 0:
            verdict = "INVALID"
            detail = f"target test fails on the clean tree (rc={rc_clean})"
            print(
                f"    clean run: rc={rc_clean} "
                f"{failed_line(out_clean, mut['node']) or last_line(out_clean)}",
                flush=True,
            )
            return verdict, detail, digest

        # (3) an ambiguous fragment makes the mutation meaningless
        occurrences = original.count(mut["old"].encode())
        if occurrences != 1:
            verdict = "INVALID"
            detail = f"fragment occurs {occurrences} times, expected exactly 1"
            return verdict, detail, digest

        # (4) mutate and run the same node again
        path.write_bytes(original.replace(mut["old"].encode(), mut["new"].encode(), 1))
        print(f"    APPLIED {mut['id']}", flush=True)
        rc_mut, out_mut = run_target(mut["node"])
        summary = failed_line(out_mut, mut["node"])
        if rc_mut == 1 and summary is not None and mut["expect"] in summary:
            verdict, detail = "KILLED", summary
        else:
            verdict = "SURVIVED"
            detail = f"rc={rc_mut}, FAILED line: {summary or last_line(out_mut)}"
        return verdict, detail, digest
    finally:
        # (5) restore, and prove it by sha256
        path.write_bytes(original)
        restored = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"    RESTORED sha256={restored} match={restored == digest}", flush=True)
        if restored != digest:
            raise SystemExit(f"{mut['id']}: FAILED TO RESTORE {mut['path']}")


def main(argv):
    groups = argv[1:] or list(GROUPS)
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        print(f"unknown group(s): {', '.join(unknown)}; known: {' '.join(GROUPS)}")
        return 2

    selected = [m for m in MUTATIONS if m["group"] in groups]
    print(f"groups: {' '.join(groups)}; mutations: {len(selected)}", flush=True)

    results = []
    for mut in selected:
        verdict, detail, _ = apply_mutation(mut)
        label = {"KILLED": "убит", "SURVIVED": "выжил", "INVALID": "неприменим"}[verdict]
        print(f"{label} ({verdict}) {mut['id']}: {detail}", flush=True)
        results.append((mut["id"], verdict))

    killed = [i for i, v in results if v == "KILLED"]
    survived = [i for i, v in results if v == "SURVIVED"]
    invalid = [i for i, v in results if v == "INVALID"]
    print(
        f"\nитог: убито {len(killed)}/{len(results)}"
        + (f"; ВЫЖИЛИ: {', '.join(survived)}" if survived else "")
        + (f"; НЕПРИМЕНИМЫ: {', '.join(invalid)}" if invalid else "")
    )
    print(f"KILLED={len(killed)} SURVIVED={len(survived)} INVALID={len(invalid)}")
    return 0 if results and not survived and not invalid else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
