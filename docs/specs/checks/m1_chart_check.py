#!/usr/bin/env python3
"""Chart checker for milestone m1-hardening (docs/specs/m1-hardening.md).

Written by the spec author, NOT by the executor: do not edit it.
Stdlib only on the host. Renders chart/ with alpine/helm in Docker and turns
the YAML into JSON with PyYAML inside the project image (anticaptcha:m1, built
by the full-suite criterion). Exit code 0 only if every check passes.

usage (from the repo root): python3 docs/specs/checks/m1_chart_check.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HELM_IMAGE = "alpine/helm:4.3.1"
PY_IMAGE = "anticaptcha:m1"
ADMIN = "ANTICAPTCHA_ADMIN_TOKEN"
HB_ENV = "ANTICAPTCHA_WORKER_HEARTBEAT_FILE"
PROBE_CMD = ["python", "-m", "workers.heartbeat", "--check", "--max-age"]

SCENARIOS = {
    "none": [],
    "a": ["--set", "existingSecret=a"],
    "ab": ["--set", "existingSecret=a", "--set", "worker.existingSecret=b"],
    "probe": ["--set", "worker.livenessProbe.maxAgeSeconds=999",
              "--set", "worker.livenessProbe.periodSeconds=7",
              "--set", "worker.heartbeatFile=/tmp/hb-x"],
    "off": ["--set", "worker.livenessProbe.enabled=false"],
}

TO_JSON = (
    "import glob, json, os, sys, yaml\n"
    "out = {}\n"
    "for p in sorted(glob.glob('/r/*.yaml')):\n"
    "    with open(p) as f:\n"
    "        out[os.path.basename(p)[:-5]] = [d for d in yaml.safe_load_all(f) if d]\n"
    "json.dump(out, sys.stdout)\n"
)

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def helm(chart, args):
    uid = f"{os.getuid()}:{os.getgid()}"
    return run(["docker", "run", "--rm", "--network", "none", "-u", uid,
                "-e", "HOME=/tmp", "-v", f"{chart}:/chart:ro", HELM_IMAGE] + args)


def containers(docs, component):
    for d in docs:
        if d.get("kind") == "Deployment" and \
                d["metadata"]["labels"].get("app.kubernetes.io/component") == component:
            return d["spec"]["template"]["spec"]["containers"]
    return None


def secret_refs(c):
    return [e["secretRef"]["name"] for e in c.get("envFrom") or [] if "secretRef" in e]


def env_map(c):
    return {e["name"]: e for e in c.get("env") or []}


def main():
    chart = pathlib.Path("chart").resolve()
    if not (chart / "Chart.yaml").is_file():
        print("FAIL run from the repo root: chart/Chart.yaml not found")
        return 1
    lint = helm(chart, ["lint", "/chart", "--set", "existingSecret=a",
                        "--set", "worker.existingSecret=b"])
    check(lint.returncode == 0, f"helm lint rc={lint.returncode} {lint.stderr.strip()[-300:]}")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="m1-chart-"))
    os.chmod(tmp, 0o755)
    for name, args in SCENARIOS.items():
        r = helm(chart, ["template", "t", "/chart"] + args)
        if r.returncode != 0:
            check(False, f"helm template [{name}] rc={r.returncode}: {r.stderr.strip()[-300:]}")
            return 1
        p = tmp / f"{name}.yaml"
        p.write_text(r.stdout)
        os.chmod(p, 0o644)
    conv = run(["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/r:ro",
                "--entrypoint", "python", PY_IMAGE, "-c", TO_JSON])
    if conv.returncode != 0:
        print(f"FAIL yaml->json in {PY_IMAGE} rc={conv.returncode}: {conv.stderr.strip()[-300:]}"
              f" (image missing? build it: docker build -t {PY_IMAGE} .)")
        return 1
    rendered = json.loads(conv.stdout)

    def pair(name):
        api, wrk = containers(rendered[name], "api"), containers(rendered[name], "worker")
        check(api is not None and wrk is not None, f"[{name}] both api and worker Deployments rendered")
        if api is None or wrk is None:
            return None, None
        check(len(api) == 1 and len(wrk) == 1, f"[{name}] one container per Deployment")
        return api[0], wrk[0]

    # Secrets: backward compatible, worker can get its own secret, never the admin token.
    api, wrk = pair("none")
    if api:
        check(secret_refs(api) == [] and secret_refs(wrk) == [], "[none] no secretRef in either")
        check(ADMIN in env_map(api), "[none] api env still has ANTICAPTCHA_ADMIN_TOKEN (default values)")
        check("BAILIAN_CODING_PLAN_API_KEY" in env_map(wrk), "[none] worker env keeps BAILIAN_CODING_PLAN_API_KEY")
        we = env_map(wrk)
        check(we.get(HB_ENV, {}).get("value") == "/tmp/worker-heartbeat",
              f"[none] worker env {HB_ENV}=/tmp/worker-heartbeat, got {we.get(HB_ENV)}")
        check(HB_ENV not in env_map(api), f"[none] api env has no {HB_ENV}")
        lp, sp = wrk.get("livenessProbe") or {}, wrk.get("startupProbe") or {}
        check(lp.get("exec", {}).get("command") == PROBE_CMD + ["300"],
              f"[none] worker livenessProbe exec = {PROBE_CMD + ['300']}, got {lp}")
        check((lp.get("periodSeconds"), lp.get("timeoutSeconds"), lp.get("failureThreshold")) == (30, 10, 3),
              f"[none] worker livenessProbe period/timeout/failure = 30/10/3, got {lp}")
        check(sp.get("exec", {}).get("command") == PROBE_CMD + ["300"],
              f"[none] worker startupProbe exec = {PROBE_CMD + ['300']}, got {sp}")
        check((sp.get("periodSeconds"), sp.get("timeoutSeconds"), sp.get("failureThreshold")) == (10, 10, 60),
              f"[none] worker startupProbe period/timeout/failure = 10/10/60, got {sp}")
        check((api.get("livenessProbe") or {}).get("httpGet", {}).get("path") == "/health",
              "[none] api livenessProbe is still httpGet /health")
        check("startupProbe" not in api, "[none] api has no startupProbe")
    for name, exp_api, exp_wrk in (("a", ["a"], ["a"]), ("ab", ["a"], ["b"])):
        api, wrk = pair(name)
        if api:
            check(secret_refs(api) == exp_api, f"[{name}] api secretRef {exp_api}, got {secret_refs(api)}")
            check(secret_refs(wrk) == exp_wrk, f"[{name}] worker secretRef {exp_wrk}, got {secret_refs(wrk)}")
    for name in SCENARIOS:
        api, wrk = pair(name)
        if wrk:
            check(ADMIN not in env_map(wrk), f"[{name}] worker env has no {ADMIN}")
    api, wrk = pair("probe")
    if wrk:
        lp, sp = wrk.get("livenessProbe") or {}, wrk.get("startupProbe") or {}
        check(lp.get("exec", {}).get("command") == PROBE_CMD + ["999"] and lp.get("periodSeconds") == 7,
              f"[probe] livenessProbe follows values (max-age 999, period 7), got {lp}")
        check(sp.get("exec", {}).get("command") == PROBE_CMD + ["999"],
              f"[probe] startupProbe uses the same max-age 999, got {sp}")
        check(env_map(wrk).get(HB_ENV, {}).get("value") == "/tmp/hb-x",
              f"[probe] worker env {HB_ENV} follows worker.heartbeatFile")
    api, wrk = pair("off")
    if wrk:
        check("livenessProbe" not in wrk and "startupProbe" not in wrk,
              "[off] worker.livenessProbe.enabled=false removes worker liveness and startup probes")
        check((api.get("livenessProbe") or {}).get("httpGet", {}).get("path") == "/health",
              "[off] api livenessProbe untouched")

    print(f"\n{'PASS' if not failures else 'FAILED'}: {len(failures)} failed check(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
