#!/usr/bin/env python3
"""Measure the production web container under a chosen memory limit.

    python infra/production-smoke/measure_web.py --runs 3 --memory-limit 512m \
        --json docs/evidence/production-envelope.json --append

The API's envelope is measured by `measure.py`; this answers the separate and
much smaller question of what the Next.js standalone server actually needs, so
its hosting tier is chosen from a measurement rather than from a round number.

Each run recreates the web service alone against the already-running API, then
records, from `compose up` on the host's monotonic clock:

* time to the container's Docker health check passing, and to the first 200
  from `/api/healthz`;
* time to the landing page rendering, with its size;
* the container's own memory — VmRSS summed over every process inside it and
  the cgroup figure `docker stats` reports, which is what a hosting limit is
  enforced against — sampled once a second, plus each process's VmHWM;
* that the running process is the production server and not `next dev`;
* that the security headers are intact and the baked API origin is right;
* whether Docker OOM-killed or restarted the container.

A run that fails any of those is written down as failed, with the reason. The
point of the exercise is to find out whether a tier is safe, and a measurement
that quietly drops its failures cannot answer that.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure import (  # noqa: E402  - shares the API harness's Docker helpers
    PROJECT,
    compose,
    container_rss_mb,
    container_stats,
    environment_facts,
    http_get,
    image_facts,
    inspect,
    sh,
)

WEB_CONTAINER = f"{PROJECT}-web-1"

#: Set by next.config.ts on every response. A production build that lost them
#: would be a regression worth failing a memory trial over.
REQUIRED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


@dataclass
class WebRun:
    label: str
    memory_limit: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    seconds_to_healthy: float | None = None
    seconds_to_healthz: float | None = None
    seconds_to_page: float | None = None
    page_bytes: int | None = None
    page_ms: float | None = None
    rss_peak_mb: float | None = None
    rss_steady_mb: float | None = None
    hwm_sum_mb: float | None = None
    cgroup_peak_mb: float | None = None
    cgroup_steady_mb: float | None = None
    limit_mb: float | None = None
    headroom_percent: float | None = None
    process_count: int | None = None
    server_command: str | None = None
    node_env: str | None = None
    api_origin_in_page: bool | None = None
    headers_present: bool | None = None
    oom_killed: bool = False
    restart_count: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.failures.append(reason)


def wait_for_health(container: str, *, timeout_s: float, started: float) -> float | None:
    """Seconds until Docker's own health check reports healthy."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = inspect(container, "{{.State.Health.Status}}")
        if status == "healthy":
            return round(time.monotonic() - started, 2)
        if status == "unhealthy":
            return None
        time.sleep(0.5)
    return None


def wait_for_200(url: str, *, timeout_s: float, started: float) -> tuple[float | None, bytes]:
    deadline = time.monotonic() + timeout_s
    body = b""
    while time.monotonic() < deadline:
        status, body = http_get(url, timeout=3.0)
        if status == 200:
            return round(time.monotonic() - started, 2), body
        time.sleep(0.25)
    return None, body


def page_headers(url: str) -> dict[str, str]:
    """Response headers, lower-cased, via curl so no extra dependency is needed."""
    raw = sh(["curl", "-s", "-D", "-", "-o", "/dev/null", url], check=False)
    headers: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
    return headers


def one_run(
    label: str,
    *,
    memory_limit: str,
    web_port: int,
    api_port: int,
    timeout_s: float,
    idle_seconds: float,
) -> WebRun:
    run = WebRun(label=label, memory_limit=memory_limit)
    env = {
        "ENVELOPE_WEB_MEMORY_LIMIT": memory_limit,
        "ENVELOPE_WEB_PORT": str(web_port),
        "ENVELOPE_API_PORT": str(api_port),
    }

    compose("rm", "-sf", "web", env=env, check=False)
    started = time.monotonic()
    compose("up", "-d", "--no-deps", "--no-build", "--force-recreate", "web", env=env)

    limit_bytes = int(inspect(WEB_CONTAINER, "{{.HostConfig.Memory}}") or 0)
    run.limit_mb = round(limit_bytes / 1_048_576, 1) if limit_bytes else None
    if not limit_bytes:
        run.fail("no memory limit was applied to the container")

    samples: list[dict[str, Any]] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            rss = container_rss_mb(WEB_CONTAINER)
            stats = container_stats(WEB_CONTAINER)
            samples.append({"t": round(time.monotonic() - started, 2), **rss, **stats})
            stop.wait(1.0)

    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()

    run.seconds_to_healthy = wait_for_health(WEB_CONTAINER, timeout_s=timeout_s, started=started)
    base = f"http://127.0.0.1:{web_port}"
    run.seconds_to_healthz, _ = wait_for_200(f"{base}/api/healthz", timeout_s=timeout_s, started=started)
    run.seconds_to_page, page = wait_for_200(base, timeout_s=timeout_s, started=started)
    run.page_bytes = len(page) if page else None

    if run.seconds_to_healthy is None:
        run.fail("container never reported healthy")
    if run.seconds_to_healthz is None:
        run.fail("/api/healthz never returned 200")
    if run.seconds_to_page is None:
        run.fail("landing page never returned 200")

    if page:
        text = page.decode("utf-8", "replace")
        if "PathAble AI" not in text:
            run.fail("landing page did not render the product name")
        # The API origin is baked into the client bundle at build time, so a
        # wrong one is invisible until the browser tries to call it.
        run.api_origin_in_page = f"localhost:{api_port}" in text
        if not run.api_origin_in_page:
            run.fail(f"landing page does not carry the expected API origin localhost:{api_port}")
        dev_markers = [m for m in ("webpack-hmr", "react-refresh", "__nextDevClientId") if m in text]
        if dev_markers:
            run.fail("the page carries development-build markers: " + ", ".join(dev_markers))

    headers = page_headers(base)
    missing = [
        f"{name}={headers.get(name, '<absent>')}"
        for name, expected in REQUIRED_HEADERS.items()
        if headers.get(name) != expected
    ]
    run.headers_present = not missing
    if missing:
        run.fail("security headers wrong or absent: " + ", ".join(missing))
    if "x-powered-by" in headers:
        run.fail("x-powered-by is present; poweredByHeader should be off")

    # Production, not a dev server. Four independent signals, because the
    # obvious one is misleading: the standalone server renames itself to
    # "next-server (vX)", so pid 1's command line never mentions server.js.
    docker_cmd = inspect(WEB_CONTAINER, "{{json .Config.Cmd}}")
    title = sh(
        ["docker", "exec", WEB_CONTAINER, "sh", "-c", "tr '\\0' ' ' < /proc/1/cmdline"], check=False
    ).strip()
    run.server_command = f"{docker_cmd} -> {title!r}"
    if "server.js" not in docker_cmd:
        run.fail(f"the container is not started from the standalone server: {docker_cmd}")
    if not title.startswith("next-server"):
        run.fail(f"pid 1 is not the Next.js production server: {title!r}")
    if "dev" in title.lower():
        run.fail(f"pid 1 looks like a development server: {title!r}")
    # The runtime image carries no Next CLI at all, so `next dev` is not merely
    # absent — it is impossible. Worth asserting: it is the reason the first
    # three signals cannot be circumvented by configuration.
    has_cli = sh(
        ["docker", "exec", WEB_CONTAINER, "sh", "-c", "test -x node_modules/.bin/next && echo yes || echo no"],
        check=False,
    ).strip()
    if has_cli != "no":
        run.fail("the runtime image contains a Next CLI; a dev server could be started in it")
    node_env = sh(
        ["docker", "exec", WEB_CONTAINER, "sh", "-c", "printenv NODE_ENV || true"], check=False
    ).strip()
    run.node_env = node_env
    if node_env != "production":
        run.fail(f"NODE_ENV is {node_env!r}, not 'production'")

    # A few page loads, so the steady figure is after the server has served.
    timings: list[float] = []
    for _ in range(5):
        began = time.perf_counter()
        status, body = http_get(base, timeout=10.0)
        timings.append((time.perf_counter() - began) * 1000)
        if status != 200:
            run.fail(f"a repeat page load returned {status}")
    run.page_ms = round(statistics.median(timings), 1)

    time.sleep(idle_seconds)
    stop.set()
    thread.join(timeout=5)
    run.samples = samples

    rss_values = [s["rss_mb"] for s in samples if s.get("rss_mb")]
    cgroup_values = [s["cgroup_memory_mb"] for s in samples if s.get("cgroup_memory_mb")]
    if rss_values:
        run.rss_peak_mb = max(rss_values)
    if cgroup_values:
        run.cgroup_peak_mb = max(cgroup_values)
    steady = container_rss_mb(WEB_CONTAINER)
    run.rss_steady_mb = steady["rss_mb"]
    run.hwm_sum_mb = steady["hwm_mb"]
    run.process_count = int(steady["processes"])
    stats = container_stats(WEB_CONTAINER)
    if stats.get("cgroup_memory_mb"):
        run.cgroup_steady_mb = float(stats["cgroup_memory_mb"])
    if run.limit_mb and run.cgroup_peak_mb:
        run.headroom_percent = round(100.0 * (run.limit_mb - run.cgroup_peak_mb) / run.limit_mb, 1)

    run.oom_killed = inspect(WEB_CONTAINER, "{{.State.OOMKilled}}") == "true"
    run.restart_count = int(inspect(WEB_CONTAINER, "{{.RestartCount}}") or 0)
    if run.oom_killed:
        run.fail("container was OOM-killed")
    if run.restart_count:
        run.fail(f"container restarted {run.restart_count}x during the run")
    if inspect(WEB_CONTAINER, "{{.State.Status}}") != "running":
        run.fail("container is not running at the end of the run")
    return run


def summarise(runs: list[WebRun]) -> dict[str, Any]:
    passed = [r for r in runs if r.passed]

    def med(values: list[float | None]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(statistics.median(clean), 2) if clean else None

    return {
        "runs": len(runs),
        "passed_runs": len(passed),
        "median_seconds_to_healthy": med([r.seconds_to_healthy for r in passed]),
        "median_seconds_to_page": med([r.seconds_to_page for r in passed]),
        "median_page_ms": med([r.page_ms for r in passed]),
        "median_rss_steady_mb": med([r.rss_steady_mb for r in passed]),
        "max_rss_peak_mb": max((r.rss_peak_mb or 0) for r in passed) if passed else None,
        "max_hwm_sum_mb": max((r.hwm_sum_mb or 0) for r in passed) if passed else None,
        "max_cgroup_peak_mb": max((r.cgroup_peak_mb or 0) for r in passed) if passed else None,
        "median_cgroup_steady_mb": med([r.cgroup_steady_mb for r in passed]),
        "min_headroom_percent": min((r.headroom_percent or 0) for r in passed) if passed else None,
        "oom_kills": sum(1 for r in runs if r.oom_killed),
        "restarts": sum(r.restart_count for r in runs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--memory-limit", default="512m")
    parser.add_argument("--label", default=None, help="Defaults to web-<limit>.")
    parser.add_argument("--web-port", type=int, default=3001)
    parser.add_argument("--api-port", type=int, default=8001)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--idle-seconds", type=float, default=10.0)
    parser.add_argument("--json", required=True)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    label = args.label or f"web-{args.memory_limit}"
    out_path = Path(args.json)
    report: dict[str, Any] = {}
    if args.append and out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
    report.setdefault("environment", environment_facts())
    report.setdefault("images", image_facts())

    runs: list[WebRun] = []
    for index in range(args.runs):
        run_label = f"{label}/run{index + 1}"
        print(f"== web cold start {run_label}", flush=True)
        run = one_run(
            run_label,
            memory_limit=args.memory_limit,
            web_port=args.web_port,
            api_port=args.api_port,
            timeout_s=args.timeout,
            idle_seconds=args.idle_seconds,
        )
        runs.append(run)
        print(
            f"   healthy {run.seconds_to_healthy}s page {run.seconds_to_page}s ({run.page_bytes} B, "
            f"{run.page_ms} ms) rss peak {run.rss_peak_mb} steady {run.rss_steady_mb} hwm {run.hwm_sum_mb} "
            f"cgroup peak {run.cgroup_peak_mb}/{run.limit_mb} MB headroom {run.headroom_percent}% "
            f"passed={run.passed} {'; '.join(run.failures)}",
            flush=True,
        )

    report.setdefault("web_batches", {})[label] = {
        "memory_limit": args.memory_limit,
        "measured_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "summary": summarise(runs),
        "runs": [asdict(r) for r in runs],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return 0 if all(r.passed for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
