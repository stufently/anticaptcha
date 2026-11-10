#!/usr/bin/env python3
"""Mutation gate for milestone m1-hardening (docs/specs/m1-hardening.md).

Host side, standard library only:

    python3 tests/mutation_gate_m1.py <group> [<group> ...]

Groups: image, worker, browser, vision, version.

For every mutation, strictly in this order:

  1. save the file bytes and their sha256;
  2. run the TARGET test on the clean tree - it must pass, otherwise the
     mutation is INVALID and does not count;
  3. check that the replaced fragment occurs in the file exactly once;
  4. apply the replacement and run the same test node again;
  5. restore the saved bytes in a `finally` block and verify the sha256;
  6. the mutant is KILLED when the clean run passed, pytest returned rc 1 on
     the mutant, and the `FAILED <node> - ...` line of the `-rf` summary
     contains the mutation's `expect` substring - the assertion message of the
     test itself (or `DID NOT RAISE`), never the name of a crash exception.

The test command is the one from the spec's "Где работать" section plus `-rf`
and `COLUMNS=1000`: pytest 7.4.3 truncates the short summary line to the
terminal width, and the default 80 columns cut away the very assertion message
that `expect` has to match.

Exit code is 0 only when every mutation of the requested groups is killed.
"""
import hashlib
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = "anticaptcha:m1"
MOUNTS = ("tests", "app", "workers", "config", "chart")
GROUPS = ("image", "worker", "browser", "vision", "version")

MUTATIONS = [
    # --- image: client image size limits -----------------------------------
    dict(
        id="IMG-1",
        group="image",
        path="workers/solvers/image_text.py",
        old="        check_image_dimensions(image_bytes)\n\n        cv2 = self.cv2\n",
        new="        cv2 = self.cv2\n",
        node="tests/test_image_limits.py::test_png_bomb_rejected_before_decode",
        expect="png bomb must be rejected before decode",
    ),
    dict(
        id="IMG-2",
        group="image",
        path="workers/solvers/image_text.py",
        old="    if width * height > max_pixels:\n",
        new="    if False:\n",
        node="tests/test_image_limits.py::test_pixel_limit_without_side_limit",
        expect="pixel limit must reject 3000x3000",
    ),
    dict(
        id="IMG-3",
        group="image",
        path="workers/solvers/image_text.py",
        old="    if max(width, height) > max_side:\n",
        new="    if False:\n",
        node="tests/test_image_limits.py::test_side_limit_without_pixel_limit",
        expect="side limit must reject 4097x10",
    ),
    dict(
        id="IMG-4",
        group="image",
        path="workers/solvers/image_text.py",
        old="    max_pixels = settings.max_image_pixels\n"
            "    max_side = settings.max_image_side\n",
        new="    max_pixels = 4_000_000\n"
            "    max_side = 4096\n",
        node="tests/test_image_limits.py::test_limits_configurable",
        expect="11x10 task must fail under tightened limits",
    ),
    dict(
        id="IMG-5",
        group="image",
        path="workers/solvers/image_text.py",
        old='    except Exception as exc:\n'
            '        raise ValueError(\n'
            '            f"Unsupported or corrupt image: {type(exc).__name__}: {exc}"\n'
            '        ) from None\n',
        new="    except Exception:\n"
            "        return (0, 0)\n",
        node="tests/test_image_limits.py::test_corrupt_header_fails",
        expect="corrupt header must be reported as unsupported",
    ),
    # --- worker: startup and heartbeat ------------------------------------
    dict(
        id="WRK-1",
        group="worker",
        path="workers/task_worker.py",
        old="        # is fatal on purpose: without tables there is nothing to work on.\n"
            "        init_db()\n",
        new="        # is fatal on purpose: without tables there is nothing to work on.\n",
        node="tests/test_worker_startup.py::test_run_on_fresh_database_creates_tables",
        expect="worker must create the tasks table",
    ),
    dict(
        id="WRK-2",
        group="worker",
        path="workers/task_worker.py",
        old="        try:\n"
            "            self.recover_interrupted_tasks()\n"
            "        except Exception as exc:\n"
            "            # Recovery is best-effort: a locked or damaged database must not\n"
            "            # keep the worker from serving new tasks.\n"
            "            print(\n"
            '                f"⚠️ Recovery of interrupted tasks failed: {type(exc).__name__}: {exc}",\n'
            "                flush=True,\n"
            "            )\n",
        new="        self.recover_interrupted_tasks()\n",
        node="tests/test_worker_startup.py::test_recovery_error_does_not_stop_worker",
        expect="recovery error must not escape run()",
    ),
    dict(
        id="HB-1",
        group="worker",
        path="workers/heartbeat.py",
        old="    while True:\n        try:\n            beat(path)\n",
        new="    if True:\n        try:\n            beat(path)\n",
        node="tests/test_heartbeat.py::test_heartbeat_updates_during_long_task",
        expect="heartbeat must keep updating during a long task",
    ),
    dict(
        id="HB-2",
        group="worker",
        path="workers/heartbeat.py",
        old="    return (now - stamp) <= max_age\n",
        new="    return True\n",
        node="tests/test_heartbeat.py::test_check_detects_stale_and_missing",
        expect="a stale heartbeat must fail the check",
    ),
    # --- browser: relaunching a dead Chromium -----------------------------
    dict(
        id="BR-1",
        group="browser",
        path="app/utils/browser.py",
        old="        if self._browser is not None and not self._browser.is_connected():\n"
            "            # A crashed Chromium used to stay in the cache forever: every URL\n"
            "            # task then failed until the pod was restarted. Drop it (and the\n"
            "            # context that belonged to it) and launch a fresh one.\n"
            "            self._browser = None\n"
            "            self._context = None\n"
            "\n",
        new="",
        node="tests/test_browser_reconnect.py::test_disconnected_browser_is_relaunched",
        expect="a disconnected browser must be relaunched, not reused",
    ),
    dict(
        id="BR-2",
        group="browser",
        path="app/utils/browser.py",
        old='            browser.on("disconnected", on_disconnected)\n',
        new="",
        node="tests/test_browser_reconnect.py::test_disconnect_event_resets_cached_browser",
        expect="get_browser must register a disconnected handler",
    ),
    dict(
        id="BR-3",
        group="browser",
        path="app/utils/browser.py",
        old="        if self._browser is not None and not self._browser.is_connected():\n",
        new="        if self._browser is not None and self._browser.is_connected():\n",
        node="tests/test_browser_reconnect.py::test_connected_browser_is_reused",
        expect="a healthy cached browser must be reused",
    ),
    # --- vision: the qwen sandbox -----------------------------------------
    dict(
        id="VIS-1",
        group="vision",
        path="workers/classifiers/vision_llm.py",
        old='                "--max-tool-calls", "0",\n',
        new="",
        node="tests/test_vision_llm_sandbox.py::test_qwen_command_is_tool_free",
        expect="the model must be allowed zero tool calls",
    ),
    dict(
        id="VIS-2",
        group="vision",
        path="workers/classifiers/vision_llm.py",
        old='                "--approval-mode", "plan",\n',
        new='                "--approval-mode", "auto",\n',
        node="tests/test_vision_llm_sandbox.py::test_qwen_command_is_tool_free",
        expect="the model must run in plan mode",
    ),
    dict(
        id="VIS-3",
        group="vision",
        path="workers/classifiers/vision_llm.py",
        old='    "tool_call",\n',
        new="",
        node="tests/test_vision_llm_sandbox.py::test_qwen_command_is_tool_free",
        expect="--exclude-tools must cover every tool that escapes the sandbox",
    ),
    dict(
        id="VIS-4",
        group="vision",
        path="workers/classifiers/vision_llm.py",
        old='                "--include-directories", str(self.temp_dir),\n',
        new="",
        node="tests/test_vision_llm_sandbox.py::test_qwen_command_is_tool_free",
        expect="--include-directories must point at the directory holding the image",
    ),
    dict(
        id="VIS-5",
        group="vision",
        path="workers/classifiers/vision_llm.py",
        old="            image_path.unlink(missing_ok=True)\n",
        new="            pass\n",
        node="tests/test_vision_llm_sandbox.py::test_temp_image_removed_after_failure",
        expect="a crashed CLI must not leave the image behind",
    ),
    dict(
        id="VIS-6",
        group="vision",
        path="config/qwen/settings.json",
        old='    "enableManagedAutoMemory": false,\n',
        new='    "enableManagedAutoMemory": true,\n',
        node="tests/test_vision_llm_sandbox.py::test_qwen_settings_disable_memory_agent",
        expect="the auto-memory subagent must stay disabled",
    ),
    # --- version ----------------------------------------------------------
    dict(
        id="VER-1",
        group="version",
        path="app/main.py",
        old='        "version": __version__\n',
        new='        "version": "1.0.0"\n',
        node="tests/test_version.py::test_root_version_matches_chart_app_version",
        expect="/ must report the chart appVersion",
    ),
]


def build_image():
    """One build for the whole run; dependency layers come from the host cache."""
    print(f"docker build -q -t {IMAGE} .")
    proc = subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE, "."],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        raise SystemExit(f"docker build failed with rc={proc.returncode}")
    print(f"image id: {proc.stdout.strip()}")


def run_target(node):
    """The spec's test command, with -rf and a wide terminal (see the docstring)."""
    cmd = ["docker", "run", "--rm", "--network", "none", "-e", "COLUMNS=1000"]
    for name in MOUNTS:
        cmd += ["-v", f"{REPO_ROOT / name}:/app/{name}:ro"]
    cmd += [IMAGE, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", node]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def failed_line(output, node):
    """The `FAILED <node> - ...` line of the short summary, if there is one."""
    for line in output.splitlines():
        if line.startswith("FAILED ") and node in line:
            return line.strip()
    return None


def first_line(output):
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else "<no output>"


def apply_mutation(mut):
    path = REPO_ROOT / mut["path"]
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    print(
        f"\n--- {mut['id']} [{mut['group']}] {mut['path']}"
        f"\n    target: {mut['node']}\n    expect: {mut['expect']}"
    )

    verdict, detail = "INVALID", ""
    try:
        # (2) the target test must pass on the clean tree
        rc_clean, out_clean = run_target(mut["node"])
        if rc_clean != 0:
            verdict = "INVALID"
            detail = f"target test fails on the clean tree (rc={rc_clean})"
            print(f"    clean run: rc={rc_clean} {failed_line(out_clean, mut['node']) or first_line(out_clean)}")
            return verdict, detail, digest

        # (3) the fragment must be unique, or the mutation is ambiguous
        occurrences = original.count(mut["old"].encode())
        if occurrences != 1:
            verdict = "INVALID"
            detail = f"fragment occurs {occurrences} times, expected exactly 1"
            return verdict, detail, digest

        # (4) mutate and run the same node
        path.write_bytes(original.replace(mut["old"].encode(), mut["new"].encode(), 1))
        rc_mut, out_mut = run_target(mut["node"])
        summary = failed_line(out_mut, mut["node"])
        if rc_mut == 1 and summary is not None and mut["expect"] in summary:
            verdict, detail = "KILLED", summary
        else:
            verdict = "SURVIVED"
            detail = f"rc={rc_mut}, FAILED line: {summary or first_line(out_mut)}"
        return verdict, detail, digest
    finally:
        # (5) restore, and prove it by sha256
        path.write_bytes(original)
        restored = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"    restored sha256 {restored} match={restored == digest}")
        if restored != digest:
            raise SystemExit(f"{mut['id']}: FAILED TO RESTORE {mut['path']}")


def main(argv):
    groups = argv[1:]
    if not groups:
        print(__doc__.strip().splitlines()[2])
        print(f"groups: {' '.join(GROUPS)}")
        return 2
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        print(f"unknown group(s): {', '.join(unknown)}; known: {', '.join(GROUPS)}")
        return 2

    selected = [m for m in MUTATIONS if m["group"] in groups]
    build_image()

    results = []
    for mut in selected:
        verdict, detail, _ = apply_mutation(mut)
        print(f"{verdict} {mut['id']}: {detail}")
        results.append((mut["id"], verdict))

    killed = [i for i, v in results if v == "KILLED"]
    survived = [i for i, v in results if v == "SURVIVED"]
    invalid = [i for i, v in results if v == "INVALID"]
    print(
        f"\ngroups: {' '.join(groups)}; killed {len(killed)}/{len(results)}"
        + (f"; SURVIVED: {', '.join(survived)}" if survived else "")
        + (f"; INVALID: {', '.join(invalid)}" if invalid else "")
    )
    return 0 if not survived and not invalid and results else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
