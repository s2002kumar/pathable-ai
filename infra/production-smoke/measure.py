#!/usr/bin/env python3
"""Measure the production API's resource envelope in the isolated Compose stack.

Standard library only, so it runs with any Python 3.11+ and needs nothing from
the API's virtualenv:

    python infra/production-smoke/measure.py --runs 3 --json docs/evidence/production-envelope.json

What one *cold start* measures, in order:

1. `docker compose up --force-recreate` of the API service alone, under the
   memory limit given by ENVELOPE_API_MEMORY_LIMIT (the database stays up, so
   the number is the API's own start, not PostgreSQL's).
2. Wall-clock from the container's StartedAt to the first 200 from
   `/health/live`, then to the first 200 from `/health/ready` — which, with
   GRAPH_PRELOAD_REGIONS set, means the routing graph is loaded and routable.
3. Migration and graph-load durations from the container's own log lines.
4. Resident memory of every process in the container, sampled once a second
   from `/proc/<pid>/status` (VmRSS) for the whole startup, plus each process's
   VmHWM (its lifetime peak) once ready. Container-level usage from
   `docker stats` alongside, because that is what a hosting limit is enforced
   against.
5. A first route request, then warmed route requests, with their latency,
   response size, and a correctness check against the first run's answer.
6. Steady-state memory after an idle pause.

A run is recorded as invalid — never silently averaged in — when the process
was suspended (wall clock and monotonic clock disagree), when readiness never
arrived, or when Docker reports the container was OOM-killed. Everything is
written to one JSON file with the machine conditions beside the numbers.

Nothing here is a load test. The concurrency probe is a handful of requests at
a handful of levels, run to check that concurrent answers stay correct and to
see the shape of latency, not to claim capacity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = Path(__file__).resolve().parent / "compose.yaml"
PROJECT = "pathable-envelope"
API_CONTAINER = f"{PROJECT}-api-1"
DB_CONTAINER = f"{PROJECT}-db-1"

#: Two journeys from the evaluation corpus (routing/waterloo_cases.py): a short
#: campus walk and a longer cross-town trip. Longitude, latitude.
SMOKE_CASES = {
    "campus-library-to-student-life": ((-80.5424, 43.4728), (-80.5449, 43.4715)),
    "uptown-to-kitchener-city-hall": ((-80.5222, 43.4650), (-80.4925, 43.4516)),
}


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def sh(args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> str:
    import os

    merged = dict(os.environ)
    if env:
        merged.update(env)
    result = subprocess.run(args, capture_output=True, text=True, env=merged, check=False)
    if check and result.returncode != 0:
        msg = f"{' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def compose(*args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    return sh(["docker", "compose", "-f", str(COMPOSE_FILE), *args], env=env, check=check)


def inspect(container: str, template: str) -> str:
    return sh(["docker", "inspect", "--format", template, container]).strip()


def container_rss_mb(container: str) -> dict[str, float]:
    """VmRSS and VmHWM summed over every process in the container, in MB."""
    script = (
        "for p in /proc/[0-9]*; do "
        "n=$(awk '/^Name:/{print $2}' $p/status 2>/dev/null); "
        "r=$(awk '/^VmRSS:/{print $2}' $p/status 2>/dev/null); "
        "h=$(awk '/^VmHWM:/{print $2}' $p/status 2>/dev/null); "
        "[ -n \"$r\" ] && echo \"$n $r $h\"; done"
    )
    out = sh(["docker", "exec", container, "sh", "-c", script], check=False)
    rss = 0.0
    hwm = 0.0
    processes = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            processes += 1
            rss += int(parts[1]) / 1024.0
            hwm += int(parts[2]) / 1024.0
    return {"rss_mb": round(rss, 1), "hwm_mb": round(hwm, 1), "processes": float(processes)}


def container_stats(container: str) -> dict[str, float | str]:
    out = sh(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}|{{.CPUPerc}}", container],
        check=False,
    ).strip()
    if "|" not in out:
        return {}
    mem, cpu = out.split("|", 1)
    used = mem.split("/")[0].strip()
    return {"cgroup_memory": used, "cgroup_memory_mb": _to_mb(used), "cpu_percent": cpu.strip()}


def _to_mb(value: str) -> float:
    value = value.strip()
    units = {"GiB": 1024.0, "MiB": 1.0, "KiB": 1 / 1024, "GB": 1000.0, "MB": 1.0, "kB": 1 / 1000, "B": 1 / 1_000_000}
    for unit, factor in units.items():  # longest suffixes first, so "MiB" never matches "B"
        if value.endswith(unit):
            try:
                return round(float(value[: -len(unit)]) * factor, 1)
            except ValueError:
                return 0.0
    return 0.0


def parse_docker_time(value: str) -> float:
    """Docker's RFC3339 with nanoseconds -> epoch seconds."""
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    head, _, rest = value.partition(".")
    if rest:
        frac = rest[:6].ljust(6, "0")
        tz = rest[6:] if len(rest) > 6 else ""
        value = f"{head}.{frac}{tz}"
    return dt.datetime.fromisoformat(value).timestamp()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def http_get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return 0, b""


def http_post_json(url: str, payload: dict[str, Any], timeout: float = 30.0) -> tuple[int, bytes, float]:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            return response.status, body, time.perf_counter() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read(), time.perf_counter() - started
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return 0, b"", time.perf_counter() - started


def route_payload(case: str, profile: str) -> dict[str, Any]:
    origin, destination = SMOKE_CASES[case]
    return {
        "region": "waterloo",
        "origin": {"longitude": origin[0], "latitude": origin[1]},
        "destination": {"longitude": destination[0], "latitude": destination[1]},
        "profile": profile,
    }


def route_signature(body: bytes) -> dict[str, Any] | None:
    """The parts of a route answer that must not change between runs."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    signature: dict[str, Any] = {}
    for key in ("standard_route", "accessible_route"):
        route = parsed.get(key)
        signature[key] = (
            None
            if route is None
            else {
                "distance_m": route.get("distance_m"),
                "segments": len(route.get("segments", [])),
                "stairway_count": route.get("stairway_count"),
            }
        )
    signature["ml_predictions_used"] = parsed.get("ml_predictions_used")
    signature["dataset"] = (parsed.get("dataset") or {}).get("checksum")
    return signature


# ---------------------------------------------------------------------------
# One cold start
# ---------------------------------------------------------------------------


@dataclass
class ColdStart:
    label: str
    memory_limit: str
    command: str
    valid: bool = True
    invalid_reason: str | None = None
    started_at_utc: str = ""
    seconds_to_live: float | None = None
    seconds_to_ready: float | None = None
    migration_seconds: float | None = None
    graph_load_seconds: float | None = None
    graph_detail: str | None = None
    rss_before_graph_load_mb: float | None = None
    rss_peak_mb: float | None = None
    hwm_sum_at_ready_mb: float | None = None
    rss_at_ready_mb: float | None = None
    rss_steady_mb: float | None = None
    cgroup_peak_mb: float | None = None
    cgroup_steady_mb: float | None = None
    process_count: int | None = None
    first_route: dict[str, Any] | None = None
    warm_routes: dict[str, Any] | None = None
    oom_killed: bool = False
    restart_count: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)


def wait_for(url: str, *, timeout_s: float, interval: float = 0.25) -> float | None:
    """Poll until a 200; returns the host monotonic time it was first seen."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status, _ = http_get(url, timeout=2.0)
        if status == 200:
            return time.monotonic()
        time.sleep(interval)
    return None


def log_marker_epoch(logs: str, marker: str) -> float | None:
    for line in logs.splitlines():
        if marker in line and "api-entrypoint" in line:
            stamp = line.split(" ", 1)[0]
            try:
                return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def cold_start(
    label: str,
    *,
    api_port: int,
    memory_limit: str,
    command: str,
    ready_timeout_s: float,
    idle_seconds: float,
    reference: dict[str, dict[str, Any] | None],
) -> ColdStart:
    result = ColdStart(label=label, memory_limit=memory_limit, command=command)
    env = {"ENVELOPE_API_MEMORY_LIMIT": memory_limit, "ENVELOPE_API_COMMAND": command,
           "ENVELOPE_API_PORT": str(api_port)}

    compose("rm", "-sf", "api", env=env, check=False)
    wall_before = time.time()
    mono_before = time.monotonic()
    # t=0 is the moment `compose up` is issued on the host. The Docker VM's own
    # clock is recorded (StartedAt) but never mixed with host timestamps: it was
    # observed a day adrift from the host during this work. The command's own
    # overhead (about a second) is therefore inside every start-to-* figure.
    t0 = time.monotonic()
    compose("up", "-d", "--no-deps", "--force-recreate", "api", env=env)
    result.started_at_utc = inspect(API_CONTAINER, "{{.State.StartedAt}}")
    started_at = t0
    base = f"http://127.0.0.1:{api_port}/api/v1"

    # Sample memory in the background while the start proceeds.
    samples: list[dict[str, Any]] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            rss = container_rss_mb(API_CONTAINER)
            stats = container_stats(API_CONTAINER)
            samples.append({"t": round(time.monotonic() - started_at, 2), **rss, **stats})
            stop.wait(1.0)

    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()

    live_at = wait_for(f"{base}/health/live", timeout_s=ready_timeout_s)
    result.seconds_to_live = None if live_at is None else round(live_at - started_at, 2)
    ready_at = wait_for(f"{base}/health/ready", timeout_s=ready_timeout_s)
    result.seconds_to_ready = None if ready_at is None else round(ready_at - started_at, 2)

    stop.set()
    thread.join(timeout=5)
    result.samples = samples

    logs = sh(["docker", "logs", API_CONTAINER], check=False) + sh(
        ["docker", "logs", API_CONTAINER], check=False
    )
    applying = log_marker_epoch(logs, "applying migrations")
    applied = log_marker_epoch(logs, "migrations applied")
    if applying is not None and applied is not None and 0 <= applied - applying <= 600:
        result.migration_seconds = round(applied - applying, 1)

    result.oom_killed = inspect(API_CONTAINER, "{{.State.OOMKilled}}") == "true"
    result.restart_count = int(inspect(API_CONTAINER, "{{.RestartCount}}") or 0)

    if ready_at is None:
        result.valid = False
        result.invalid_reason = (
            "OOM-killed" if result.oom_killed else f"not ready within {ready_timeout_s:.0f} s"
        )
        if result.restart_count:
            result.invalid_reason += f" (restarted {result.restart_count}x)"
        return result

    status, body = http_get(f"{base}/health/ready")
    try:
        ready_body = json.loads(body)
        graph = ready_body["checks"]["graph"]
        result.graph_detail = graph.get("detail")
        if graph.get("latency_ms") is not None:
            result.graph_load_seconds = round(graph["latency_ms"] / 1000.0, 2)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Memory: peak of the sampled RSS during startup; the sample just before the
    # graph began loading is the one taken at liveness.
    rss_values = [s["rss_mb"] for s in samples if s.get("rss_mb")]
    if rss_values:
        result.rss_peak_mb = max(rss_values)
    live_samples = [s for s in samples if result.seconds_to_live is not None and s["t"] <= result.seconds_to_live + 0.5]
    if live_samples:
        result.rss_before_graph_load_mb = live_samples[-1]["rss_mb"]
    cgroup_values = [s["cgroup_memory_mb"] for s in samples if s.get("cgroup_memory_mb")]
    if cgroup_values:
        result.cgroup_peak_mb = max(cgroup_values)

    at_ready = container_rss_mb(API_CONTAINER)
    result.rss_at_ready_mb = at_ready["rss_mb"]
    result.hwm_sum_at_ready_mb = at_ready["hwm_mb"]
    result.process_count = int(at_ready["processes"])

    # First route, then warm routes.
    first_status, first_body, first_seconds = http_post_json(
        f"{base}/routes/compare", route_payload("campus-library-to-student-life", "wheelchair")
    )
    signature = route_signature(first_body)
    result.first_route = {
        "case": "campus-library-to-student-life",
        "profile": "wheelchair",
        "status": first_status,
        "seconds": round(first_seconds, 3),
        "response_bytes": len(first_body),
        "signature": signature,
    }
    warm = warm_routes(base, reference)
    result.warm_routes = warm

    time.sleep(idle_seconds)
    steady = container_rss_mb(API_CONTAINER)
    result.rss_steady_mb = steady["rss_mb"]
    stats = container_stats(API_CONTAINER)
    if stats.get("cgroup_memory_mb"):
        result.cgroup_steady_mb = float(stats["cgroup_memory_mb"])

    # Suspend detection: a suspended laptop advances the wall clock without the
    # monotonic clock, and a measurement across that gap is not a measurement.
    wall_elapsed = time.time() - wall_before
    mono_elapsed = time.monotonic() - mono_before
    if abs(wall_elapsed - mono_elapsed) > 5.0:
        result.valid = False
        result.invalid_reason = "clock discontinuity during the run (system suspended?)"
    if result.oom_killed or result.restart_count:
        result.valid = False
        result.invalid_reason = f"container restarted {result.restart_count}x during the run"
    return result


#: Two selectable profiles. Every comparison carries the shortest walking route
#: as its baseline, so "standard" is not a choice the endpoint accepts.
SMOKE_PROFILES = ("wheelchair", "stroller")


def warm_routes(base: str, reference: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """Five warmed requests per case and profile: latency, size, and stability."""
    warm: dict[str, Any] = {}
    for case in SMOKE_CASES:
        for profile in SMOKE_PROFILES:
            timings: list[float] = []
            sizes: list[int] = []
            statuses: set[int] = set()
            sig: dict[str, Any] | None = None
            for _ in range(5):
                status, body, seconds = http_post_json(f"{base}/routes/compare", route_payload(case, profile))
                timings.append(seconds)
                sizes.append(len(body))
                statuses.add(status)
                sig = route_signature(body)
            key = f"{case}/{profile}"
            expected = reference.get(key)
            if expected is None:
                reference[key] = sig
                matches = True
            else:
                matches = sig == expected
            warm[key] = {
                "statuses": sorted(statuses),
                "median_ms": round(statistics.median(timings) * 1000, 1),
                "max_ms": round(max(timings) * 1000, 1),
                "response_bytes": sizes[-1],
                "matches_reference": matches,
                "signature": sig,
            }
    return warm


# ---------------------------------------------------------------------------
# Restart / shutdown behaviour
# ---------------------------------------------------------------------------


def restart_and_shutdown(api_port: int, ready_timeout_s: float) -> dict[str, Any]:
    base = f"http://127.0.0.1:{api_port}/api/v1"
    out: dict[str, Any] = {}

    started = time.monotonic()
    sh(["docker", "restart", API_CONTAINER])
    restart_returned = time.monotonic()
    ready_at = wait_for(f"{base}/health/ready", timeout_s=ready_timeout_s)
    out["restart"] = {
        "docker_restart_seconds": round(restart_returned - started, 2),
        "seconds_to_ready_after_restart": None if ready_at is None else round(ready_at - started, 2),
    }

    # Graceful stop: SIGTERM to PID 1 (the exec'd server), then how long until exit.
    started = time.perf_counter()
    sh(["docker", "stop", "--time", "30", API_CONTAINER])
    stop_seconds = round(time.perf_counter() - started, 2)
    exit_code = inspect(API_CONTAINER, "{{.State.ExitCode}}")
    logs = sh(["docker", "logs", "--tail", "40", API_CONTAINER], check=False)
    out["stop"] = {
        "seconds": stop_seconds,
        "exit_code": int(exit_code) if exit_code.lstrip("-").isdigit() else exit_code,
        "logged_shutdown": any(marker in logs for marker in ("PathAble API stopped", "Shutting down", "Finished server process")),
    }
    return out


# ---------------------------------------------------------------------------
# Concurrency probe (small, not a load test)
# ---------------------------------------------------------------------------


def concurrency_probe(
    api_port: int, *, levels: list[int], requests_per_level: int, reference: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    base = f"http://127.0.0.1:{api_port}/api/v1"
    cases = list(SMOKE_CASES)
    profiles = SMOKE_PROFILES
    results: dict[str, Any] = {"levels": []}

    # Warm every (case, profile) pair first so no level pays a first-use cost.
    for case in cases:
        for profile in profiles:
            http_post_json(f"{base}/routes/compare", route_payload(case, profile))

    for level in levels:
        latencies: list[float] = []
        errors = 0
        timeouts = 0
        mismatches = 0
        lock = threading.Lock()
        jobs = [(cases[i % len(cases)], profiles[i % 2]) for i in range(requests_per_level * level)]
        cpu_samples: list[str] = []
        rss_samples: list[float] = []
        stop = threading.Event()

        def sampler() -> None:
            while not stop.is_set():
                stats = container_stats(API_CONTAINER)
                if stats:
                    cpu_samples.append(str(stats.get("cpu_percent", "")))
                rss_samples.append(container_rss_mb(API_CONTAINER)["rss_mb"])
                stop.wait(0.5)

        def worker(chunk: list[tuple[str, str]]) -> None:
            nonlocal errors, timeouts, mismatches
            for case, profile in chunk:
                status, body, seconds = http_post_json(f"{base}/routes/compare", route_payload(case, profile), timeout=60.0)
                sig = route_signature(body)
                with lock:
                    if status == 0:
                        timeouts += 1
                    elif status != 200:
                        errors += 1
                    else:
                        latencies.append(seconds)
                        if reference.get(f"{case}/{profile}") not in (None, sig):
                            mismatches += 1

        chunks = [jobs[i::level] for i in range(level)]
        sampler_thread = threading.Thread(target=sampler, daemon=True)
        sampler_thread.start()
        started = time.perf_counter()
        threads = [threading.Thread(target=worker, args=(chunk,)) for chunk in chunks]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.perf_counter() - started
        stop.set()
        sampler_thread.join(timeout=3)

        ordered = sorted(latencies)
        results["levels"].append(
            {
                "concurrency": level,
                "requests": len(jobs),
                "ok": len(latencies),
                "errors": errors,
                "timeouts": timeouts,
                "answer_mismatches": mismatches,
                "elapsed_s": round(elapsed, 2),
                "requests_per_second": round(len(jobs) / elapsed, 2) if elapsed else None,
                "p50_ms": round(statistics.median(ordered) * 1000, 1) if ordered else None,
                "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 1) if ordered else None,
                "max_ms": round(ordered[-1] * 1000, 1) if ordered else None,
                "cpu_percent_samples": cpu_samples,
                "rss_mb_max": max(rss_samples) if rss_samples else None,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Environment and database facts
# ---------------------------------------------------------------------------


def environment_facts() -> dict[str, Any]:
    info = json.loads(sh(["docker", "info", "--format", "{{json .}}"]))
    facts: dict[str, Any] = {
        "measured_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        "host_platform": platform.platform(),
        "host_machine": platform.machine(),
        "python": platform.python_version(),
        "docker_server_version": info.get("ServerVersion"),
        "docker_os": f"{info.get('OperatingSystem')} ({info.get('OSType')}/{info.get('Architecture')})",
        "docker_cpus": info.get("NCPU"),
        "docker_memory_total_mb": round(info.get("MemTotal", 0) / 1_000_000),
        "cgroup_version": info.get("CgroupVersion"),
    }
    try:
        import ctypes

        if sys.platform == "win32":

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            facts["host_memory_total_mb"] = round(status.ullTotalPhys / 1_000_000)
            facts["host_memory_available_mb"] = round(status.ullAvailPhys / 1_000_000)
    except Exception:  # noqa: BLE001 - best effort, never fatal
        pass
    return facts


def image_facts() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, image in (("api", f"{PROJECT}-api:local"), ("web", f"{PROJECT}-web:local")):
        try:
            raw = json.loads(sh(["docker", "image", "inspect", image]))[0]
        except (RuntimeError, IndexError, json.JSONDecodeError):
            continue
        out[name] = {
            "image": image,
            "id": raw.get("Id"),
            "size_mb": round(raw.get("Size", 0) / 1_000_000, 1),
            "user": raw.get("Config", {}).get("User"),
            "cmd": raw.get("Config", {}).get("Cmd"),
            "entrypoint": raw.get("Config", {}).get("Entrypoint"),
        }
    return out


def database_facts() -> dict[str, Any]:
    def q(sql: str) -> str:
        return sh(["docker", "exec", DB_CONTAINER, "psql", "-U", "pathable", "-d", "pathable", "-At", "-c", sql], check=False).strip()

    out: dict[str, Any] = {
        "postgres_version": q("select version()"),
        "postgis_version": q("select extversion from pg_extension where extname='postgis'"),
        "alembic_revision": q("select version_num from alembic_version"),
        "database_size": q("select pg_size_pretty(pg_database_size('pathable'))"),
        "database_size_bytes": q("select pg_database_size('pathable')"),
        "active_dataset": q(
            "select json_build_object('id', id, 'checksum', checksum, 'source_name', source_name, "
            "'node_count', node_count, 'edge_count', edge_count) from dataset_versions "
            "where status='active' and source_name like 'openstreetmap%'"
        ),
        "graph_nodes": q("select count(*) from graph_nodes"),
        "graph_edges": q("select count(*) from graph_edges"),
        "tables": [],
        "max_connections": q("show max_connections"),
    }
    rows = q(
        "select relname, pg_size_pretty(pg_total_relation_size(c.oid)), pg_total_relation_size(c.oid), "
        "pg_size_pretty(pg_relation_size(c.oid)), pg_size_pretty(pg_indexes_size(c.oid)) "
        "from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname='public' and c.relkind='r' order by pg_total_relation_size(c.oid) desc"
    )
    for row in rows.splitlines():
        parts = row.split("|")
        if len(parts) == 5:
            out["tables"].append({"table": parts[0], "total": parts[1], "total_bytes": int(parts[2]), "heap": parts[3], "indexes": parts[4]})
    try:
        out["active_dataset"] = json.loads(out["active_dataset"]) if out["active_dataset"] else None
    except json.JSONDecodeError:
        pass
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def summarise(runs: list[ColdStart]) -> dict[str, Any]:
    valid = [r for r in runs if r.valid]

    def med(values: list[float | None]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(statistics.median(clean), 2) if clean else None

    return {
        "runs": len(runs),
        "valid_runs": len(valid),
        "median_seconds_to_live": med([r.seconds_to_live for r in valid]),
        "median_seconds_to_ready": med([r.seconds_to_ready for r in valid]),
        "max_seconds_to_ready": max((r.seconds_to_ready or 0) for r in valid) if valid else None,
        "median_graph_load_seconds": med([r.graph_load_seconds for r in valid]),
        "median_migration_seconds": med([r.migration_seconds for r in valid]),
        "median_rss_before_graph_load_mb": med([r.rss_before_graph_load_mb for r in valid]),
        "max_rss_peak_mb": max((r.rss_peak_mb or 0) for r in valid) if valid else None,
        "median_rss_peak_mb": med([r.rss_peak_mb for r in valid]),
        "median_hwm_sum_at_ready_mb": med([r.hwm_sum_at_ready_mb for r in valid]),
        "median_rss_at_ready_mb": med([r.rss_at_ready_mb for r in valid]),
        "median_rss_steady_mb": med([r.rss_steady_mb for r in valid]),
        "max_cgroup_peak_mb": max((r.cgroup_peak_mb or 0) for r in valid) if valid else None,
        "median_first_route_ms": med([None if r.first_route is None else r.first_route["seconds"] * 1000 for r in valid]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3, help="Cold starts per memory limit (default 3).")
    parser.add_argument("--memory-limits", default="2g", help="Comma-separated Docker memory limits to test, e.g. 1g,1.5g,2g.")
    parser.add_argument("--command", default="python -m pathable_api", help="API container command (override to test workers).")
    parser.add_argument("--label", default="one-worker", help="Label for this batch of runs.")
    parser.add_argument("--api-port", type=int, default=8001)
    parser.add_argument("--ready-timeout", type=float, default=240.0, help="Seconds to wait for readiness before calling a run invalid.")
    parser.add_argument("--idle-seconds", type=float, default=10.0)
    parser.add_argument("--concurrency", default="1,2,4,8", help="Concurrency levels for the small probe; empty to skip.")
    parser.add_argument("--requests-per-level", type=int, default=6)
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--json", required=True, help="Write the structured report here.")
    parser.add_argument("--append", action="store_true", help="Merge into an existing report under this label instead of overwriting.")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Skip cold starts: measure warm routes and the concurrency probe against the running container, "
        "stored under the label's first memory limit without touching its recorded runs.",
    )
    args = parser.parse_args()

    limits = [item.strip() for item in args.memory_limits.split(",") if item.strip()]
    levels = [int(item) for item in args.concurrency.split(",") if item.strip()]

    report: dict[str, Any] = {}
    out_path = Path(args.json)
    if args.append and out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
    report.setdefault("environment", environment_facts())
    report.setdefault("images", image_facts())
    report.setdefault("database", database_facts())
    report.setdefault("batches", {})

    reference: dict[str, dict[str, Any] | None] = report.get("route_reference", {})
    batches: dict[str, Any] = {}
    if args.probe_only:
        limit = limits[0]
        base = f"http://127.0.0.1:{args.api_port}/api/v1"
        existing = report["batches"].setdefault(args.label, {}).setdefault(
            limit, {"memory_limit": limit, "command": args.command, "summary": None, "runs": []}
        )
        print("== warm routes", flush=True)
        existing["probe"] = {"warm_routes": warm_routes(base, reference)}
        if levels:
            print("== concurrency probe", flush=True)
            existing["probe"]["concurrency_probe"] = concurrency_probe(
                args.api_port, levels=levels, requests_per_level=args.requests_per_level, reference=reference
            )
        report["route_reference"] = reference
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out_path}")
        return 0
    for limit in limits:
        runs: list[ColdStart] = []
        for index in range(args.runs):
            label = f"{args.label}/{limit}/run{index + 1}"
            print(f"== cold start {label}", flush=True)
            run = cold_start(
                label,
                api_port=args.api_port,
                memory_limit=limit,
                command=args.command,
                ready_timeout_s=args.ready_timeout,
                idle_seconds=args.idle_seconds,
                reference=reference,
            )
            runs.append(run)
            print(
                f"   live {run.seconds_to_live}s ready {run.seconds_to_ready}s graph {run.graph_load_seconds}s "
                f"rss peak {run.rss_peak_mb} MB ready {run.rss_at_ready_mb} MB steady {run.rss_steady_mb} MB "
                f"cgroup peak {run.cgroup_peak_mb} MB valid={run.valid} {run.invalid_reason or ''}",
                flush=True,
            )
        batch: dict[str, Any] = {
            "memory_limit": limit,
            "command": args.command,
            "summary": summarise(runs),
            "runs": [asdict(r) for r in runs],
        }
        if runs and runs[-1].valid:
            if levels:
                print("== concurrency probe", flush=True)
                batch["concurrency_probe"] = concurrency_probe(
                    args.api_port, levels=levels, requests_per_level=args.requests_per_level, reference=reference
                )
            if not args.skip_restart:
                print("== restart and shutdown", flush=True)
                batch["restart_and_shutdown"] = restart_and_shutdown(args.api_port, args.ready_timeout)
        batches[limit] = batch

    report["batches"][args.label] = batches
    report["route_reference"] = reference
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
