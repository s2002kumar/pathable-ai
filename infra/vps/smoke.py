#!/usr/bin/env python3
"""Smoke-test the public PathAble deployment from outside the host.

    python infra/vps/smoke.py --url https://51.222.36.79 \
        --expect-revision a3f6448aab55 --runs 10 --concurrency 4 --json out.json

Standard library only, so it runs from any machine with Python 3.11+. Every
request goes over the public internet through Caddy, which is the point: a check
made from inside a container proves nothing about what a visitor gets.

What it checks, each recorded as passed or failed with the reason:

* TLS: the certificate validates against the client's trust store and names the
  host; plain HTTP redirects to HTTPS.
* Only 80 and 443 answer. PostgreSQL (5432), the API (8000) and the web server
  (3000) must refuse or time out.
* The landing page and planner render; the web server's security headers arrive.
* Liveness reports the expected revision; readiness says the database, PostGIS
  and the Waterloo graph are all ready.
* Place search finds both ends of the journey recorded in
  docs/evidence/waterloo-place-search.json, and routing that journey with the
  wheelchair profile reproduces the recorded answer exactly: 406.4 m with
  4 stairways on the shortest route, 490.2 m with none on the accessible one,
  from dataset 51585450 and with no model predictions.

Then latency: the route repeated sequentially, then the same with N clients in
parallel, recording the client's round trip and the server's own
``computation_ms``. Round trips include the network path from wherever this
runs, so they describe that path as much as the server.

Last, the rate limit: route requests are sent until one is refused, which must
be an HTTP 429 with a ``Retry-After`` and the ``rate_limited`` error body.

**One client's budget.** The API allows each client 30 route comparisons a
minute (KI-13), and this script is one client. The defaults spend 21 before the
rate-limit check — one for the journey, ``--runs`` sequential and ``--runs``
parallel — so ``--runs`` above 14 is refused part-way through, as is a second
run from the same address within about a minute: wait for the ``Retry-After``
the failure reports. ``--skip-rate-limit-check`` leaves the budget unspent.

Exit status is non-zero if any check failed.
"""

# ruff: noqa: S310, T201 - a command-line check: it prints its results, and opens
# only the http(s) origin it is given.

from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: The searched journey recorded by PA-SEARCH-01 against the same dataset.
JOURNEY_START_QUERY = "Davis Centre"
JOURNEY_START_LABEL = "Davis Centre Library"
JOURNEY_END_QUERY = "Student Life Centre"
JOURNEY_END_LABEL = "Student Life Centre"
EXPECTED_DATASET = "51585450-8ff5-409d-a02e-66d5a3c5e260"
EXPECTED_STANDARD = (406.4, 4)
EXPECTED_ACCESSIBLE = (490.2, 0)
PRIVATE_PORTS = (5432, 8000, 3000)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Report:
    url: str
    started_at: str
    client: str
    checks: list[Check] = field(default_factory=list)
    latency: dict[str, Any] = field(default_factory=dict)

    def record(self, name: str, passed: bool, detail: str) -> bool:
        self.checks.append(Check(name, passed, detail))
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)
        return passed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def request(
    url: str, body: dict[str, Any] | None = None, timeout: float = 30.0
) -> tuple[int, dict[str, str], bytes, float]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    req.add_header("User-Agent", "pathable-vps-smoke/1")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            status = response.status
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        payload = error.read()
        status = error.code
        headers = {k.lower(): v for k, v in error.headers.items()}
    return status, headers, payload, (time.perf_counter() - started) * 1000.0


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def summarise(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "min": round(min(values), 1),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": round(max(values), 1),
        "mean": round(statistics.fmean(values), 1),
    }


def check_tls(report: Report, host: str) -> None:
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, 443), timeout=10) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            # typeshed's union for this dict is looser than what CPython returns.
            cert: Any = tls.getpeercert() or {}
            version = tls.version()
    except (ssl.SSLError, OSError) as error:
        report.record("tls", False, f"handshake failed: {error}")
        return
    issuer = dict(item[0] for item in cert.get("issuer", ()))
    names = [value for _, value in cert.get("subjectAltName", ())]
    report.record(
        "tls",
        host in names,
        f"{version}, issuer {issuer.get('organizationName')} {issuer.get('commonName')}, "
        f"names {names}, valid until {cert.get('notAfter')}",
    )


def check_ports(report: Report, host: str) -> None:
    for port in PRIVATE_PORTS:
        try:
            with socket.create_connection((host, port), timeout=4):
                report.record(f"port {port} closed", False, "accepted a connection")
        except OSError as error:
            report.record(f"port {port} closed", True, type(error).__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="Public origin, e.g. https://51.222.36.79")
    parser.add_argument("--expect-revision", default="", help="Short or full SHA to require")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--skip-rate-limit-check",
        action="store_true",
        help="Do not spend this address's route budget proving the limit",
    )
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    base = args.url.rstrip("/")
    host = urlsplit(base).hostname or ""
    report = Report(
        url=base,
        started_at=dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
        client=socket.gethostname(),
    )

    check_tls(report, host)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(f"http://{host}/", timeout=10)
        report.record("http redirects to https", False, "plain HTTP served a page")
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location", "")
        report.record(
            "http redirects to https",
            error.code in (301, 302, 307, 308) and location.startswith("https://"),
            f"{error.code} -> {location}",
        )
    check_ports(report, host)

    status, headers, body, ms = request(f"{base}/")
    report.record(
        "landing page",
        status == 200 and b"PathAble" in body,
        f"{status}, {len(body)} bytes, {ms:.0f} ms",
    )
    wanted = {"x-content-type-options": "nosniff", "x-frame-options": "DENY"}
    missing = [k for k, v in wanted.items() if headers.get(k) != v]
    leaked = [k for k in ("server", "x-powered-by") if k in headers]
    report.record(
        "security headers",
        not missing and not leaked,
        f"missing {missing or 'none'}, leaked {leaked or 'none'}",
    )
    status, _, body, ms = request(f"{base}/planner")
    report.record("planner page", status == 200, f"{status}, {len(body)} bytes, {ms:.0f} ms")

    status, _, body, _ = request(f"{base}/api/v1/health/live")
    version = json.loads(body).get("version", "") if status == 200 else ""
    report.record(
        "liveness and revision",
        status == 200 and args.expect_revision[:12] in version,
        f"{status}, version {version}",
    )
    status, _, body, _ = request(f"{base}/api/v1/health/ready")
    ready = json.loads(body) if body else {}
    checks = {name: value.get("status") for name, value in ready.get("checks", {}).items()}
    report.record(
        "readiness", status == 200 and ready.get("status") == "ready", f"{status}, {checks}"
    )

    status, _, body, _ = request(f"{base}/api/v1/routes/profiles")
    keys = [p["key"] for p in json.loads(body).get("profiles", [])] if status == 200 else []
    report.record("profiles", "wheelchair" in keys, f"{status}, {keys}")

    ends: dict[str, dict[str, Any]] = {}
    search_ms: list[float] = []
    for query, label in (
        (JOURNEY_START_QUERY, JOURNEY_START_LABEL),
        (JOURNEY_END_QUERY, JOURNEY_END_LABEL),
    ):
        status, _, body, ms = request(
            f"{base}/api/v1/geocode/search", {"region": "waterloo", "query": query}
        )
        search_ms.append(ms)
        result = json.loads(body) if status == 200 else {}
        match = next((m for m in result.get("matches", []) if m.get("label") == label), None)
        if match is not None:
            ends[label] = match
        report.record(
            f"search '{query}'",
            status == 200 and result.get("provider") == "local" and match is not None,
            f"{status}, {len(result.get('matches', []))} matches, found {label!r}: {match is not None}, {ms:.0f} ms",
        )
    if len(ends) != 2:
        report.record("route", False, "search did not return both ends of the journey")
        return finish(report, args.json)

    route_body = {
        "region": "waterloo",
        "origin": {k: ends[JOURNEY_START_LABEL][k] for k in ("longitude", "latitude")},
        "destination": {k: ends[JOURNEY_END_LABEL][k] for k in ("longitude", "latitude")},
        "profile": "wheelchair",
    }
    status, _, body, ms = request(f"{base}/api/v1/routes/compare", route_body)
    route = json.loads(body) if status == 200 else {}
    standard = route.get("standard_route") or {}
    accessible = route.get("accessible_route") or {}
    got_standard = (round(standard.get("distance_m", -1), 1), standard.get("stairway_count"))
    got_accessible = (round(accessible.get("distance_m", -1), 1), accessible.get("stairway_count"))
    dataset = route.get("dataset", {})
    report.record(
        "searched journey, wheelchair",
        status == 200
        and got_standard == EXPECTED_STANDARD
        and got_accessible == EXPECTED_ACCESSIBLE
        and dataset.get("dataset_id") == EXPECTED_DATASET
        and route.get("ml_predictions_used") is False
        and "OpenStreetMap" in dataset.get("attribution", ""),
        f"{status}, standard {got_standard} (expected {EXPECTED_STANDARD}), accessible "
        f"{got_accessible} (expected {EXPECTED_ACCESSIBLE}), dataset {dataset.get('dataset_id')}, "
        f"ml_predictions_used {route.get('ml_predictions_used')}, {ms:.0f} ms",
    )

    def one_route() -> tuple[float, float, int]:
        status, _, body, ms = request(f"{base}/api/v1/routes/compare", route_body)
        server = 0.0
        if status == 200:
            payload = json.loads(body)
            server = sum(
                (payload.get(key) or {}).get("computation_ms", 0.0)
                for key in ("standard_route", "accessible_route")
            )
        return ms, server, status

    sequential = [one_route() for _ in range(args.runs)]
    statuses = [s for _, _, s in sequential]
    report.latency["route_sequential_round_trip_ms"] = summarise([m for m, _, _ in sequential])
    report.latency["route_server_computation_ms"] = summarise([c for _, c, _ in sequential])
    report.record(
        f"{args.runs} sequential routes",
        all(s == 200 for s in statuses),
        f"round trip {report.latency['route_sequential_round_trip_ms']}, "
        f"server {report.latency['route_server_computation_ms']}{refusals(statuses)}",
    )

    for _ in range(max(0, args.runs - len(search_ms))):
        search_ms.append(
            request(
                f"{base}/api/v1/geocode/search", {"region": "waterloo", "query": JOURNEY_END_QUERY}
            )[3]
        )
    report.latency["search_round_trip_ms"] = summarise(search_ms)

    if args.concurrency > 1:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            parallel = list(pool.map(lambda _: one_route(), range(args.runs)))
        wall = time.perf_counter() - started
        report.latency["route_parallel"] = {
            "clients": args.concurrency,
            "requests": args.runs,
            "wall_s": round(wall, 2),
            "requests_per_s": round(args.runs / wall, 2),
            "round_trip_ms": summarise([m for m, _, _ in parallel]),
        }
        report.record(
            f"{args.runs} routes, {args.concurrency} clients",
            all(s == 200 for _, _, s in parallel),
            json.dumps(report.latency["route_parallel"]) + refusals([s for _, _, s in parallel]),
        )

    if not args.skip_rate_limit_check:
        check_rate_limit(report, f"{base}/api/v1/routes/compare", route_body)

    return finish(report, args.json)


def refusals(statuses: list[int]) -> str:
    limited = statuses.count(429)
    if not limited:
        return ""
    return (
        f"; {limited} refused with 429 — this address has used its route budget, "
        "wait for the Retry-After and run again"
    )


def check_rate_limit(
    report: Report, url: str, route_body: dict[str, Any], attempts: int = 60
) -> None:
    """Spend route requests until one is refused, and check the refusal is the standard one."""
    for sent in range(1, attempts + 1):
        status, headers, body, _ = request(url, route_body)
        if status == 429:
            payload = json.loads(body) if body else {}
            retry_after = headers.get("retry-after", "")
            report.record(
                "rate limit",
                retry_after.isdigit()
                and int(retry_after) >= 1
                and payload.get("code") == "rate_limited",
                f"429 after {sent} more route requests, Retry-After {retry_after or 'missing'}, "
                f"code {payload.get('code')}",
            )
            return
        if status != 200:
            report.record("rate limit", False, f"request {sent} answered {status}, not 200 or 429")
            return
    report.record("rate limit", False, f"{attempts} more route requests and none was refused")


def finish(report: Report, path: Path | None) -> int:
    failed = [c.name for c in report.checks if not c.passed]
    print(f"\n{len(report.checks) - len(failed)}/{len(report.checks)} checks passed", flush=True)
    if path is not None:
        payload = asdict(report) | {"failed": failed}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
