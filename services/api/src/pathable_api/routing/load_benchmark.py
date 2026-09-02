"""Measuring how long a region takes to load, and how much memory it costs.

Loading the graph is the cold-start cost of the service: nothing can be routed
until it is done, and the memory it settles at is the memory an instance needs.
Both numbers have been quoted from ad-hoc scripts before. This module exists so
they come from a command anybody can rerun, with the conditions written next to
the result — a figure with no conditions attached is a number about nothing.

Three honesty rules, each of which a naive harness gets wrong:

* **Timing runs and heap runs are separate.** ``tracemalloc`` slows every
  allocation, so a load measured with it on is slower than the service will be.
  Wall-clock comes from runs without it; peak heap from runs with it; every run
  says which it was.
* **A run that was not actually running is not a measurement.** A laptop that
  suspends, or pages for minutes, produces an elapsed time that says nothing
  about the code. Such runs are kept in the output and marked invalid with the
  reason, rather than deleted or averaged in.
* **Two versions must be shown to have loaded the same graph.** A speed-up that
  quietly dropped a field would still look like a speed-up. The report carries a
  fingerprint of every node and segment so two runs can be compared for content,
  not only for time.
"""

from __future__ import annotations

import datetime as dt
import gc
import hashlib
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import get_active_dataset
from pathable_api.geo.models import PilotRegion
from pathable_api.routing.graph import NoActiveDatasetError, RoutableGraph, load_graph

#: Bumped whenever the shape of the report changes, so an old evidence file is
#: never read as if it had today's fields.
LOAD_BENCHMARK_VERSION = 1

#: A run whose wall-clock exceeds this many times its own CPU time was mostly
#: not running — suspended, or paging so hard the interpreter barely executed.
#: Loading is CPU-bound apart from a few seconds of socket wait, so an honest
#: run sits well under this even on a busy machine.
IDLE_RATIO_LIMIT = 20.0

#: Below this share of physical memory available before a run starts, the
#: machine is paging and wall-clock is measuring the disk, not the code. The run
#: is kept but flagged.
MEMORY_PRESSURE_FRACTION = 0.10


# ---------------------------------------------------------------------------
# Machine and process memory, best effort and labelled
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MachineMemory:
    total_mb: float | None
    available_mb: float | None
    method: str


@dataclass(frozen=True, slots=True)
class ProcessMemory:
    #: Resident set right now.
    rss_mb: float | None
    #: The highest resident set this process has reached so far. Process-wide,
    #: so on the second run it includes the first.
    peak_rss_mb: float | None
    method: str


#: Compared as a plain string on purpose: a platform check the type checker can
#: narrow makes every other branch "unreachable" on the machine running it.
_PLATFORM: str = sys.platform


def machine_memory() -> MachineMemory:
    """Physical memory on this machine, or ``None`` where it cannot be read."""
    if _PLATFORM == "win32":
        return _windows_machine_memory()
    if _PLATFORM.startswith("linux"):
        return _linux_machine_memory()
    return MachineMemory(None, None, "unavailable on this platform")


def process_memory() -> ProcessMemory:
    """This process's resident memory, or ``None`` where it cannot be read."""
    if _PLATFORM == "win32":
        return _windows_process_memory()
    if _PLATFORM.startswith("linux"):
        return _linux_process_memory()
    return _posix_peak_only()


def _windows_machine_memory() -> MachineMemory:  # pragma: no cover - platform specific
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return MachineMemory(None, None, "windows:GlobalMemoryStatusEx unavailable")

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return MachineMemory(
            _mb(status.ullTotalPhys), _mb(status.ullAvailPhys), "windows:GlobalMemoryStatusEx"
        )
    return MachineMemory(None, None, "windows:GlobalMemoryStatusEx failed")


def _windows_process_memory() -> ProcessMemory:  # pragma: no cover - platform specific
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return ProcessMemory(None, None, "windows:GetProcessMemoryInfo unavailable")

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(ProcessMemoryCounters)
    # Without declared argument types the pseudo-handle (-1) is truncated to a
    # 32-bit int on a 64-bit process and the call fails with ERROR_INVALID_HANDLE.
    get_current_process = windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_info = windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_ulong)
    get_info.restype = ctypes.c_int
    handle = get_current_process()
    if get_info(handle, ctypes.byref(counters), counters.cb):
        return ProcessMemory(
            _mb(counters.WorkingSetSize),
            _mb(counters.PeakWorkingSetSize),
            "windows:GetProcessMemoryInfo working set",
        )
    return ProcessMemory(None, None, "windows:GetProcessMemoryInfo failed")


def _linux_machine_memory() -> MachineMemory:  # pragma: no cover - platform specific
    values = _proc_kb(Path("/proc/meminfo"), ("MemTotal", "MemAvailable"))
    return MachineMemory(values.get("MemTotal"), values.get("MemAvailable"), "linux:/proc/meminfo")


def _linux_process_memory() -> ProcessMemory:  # pragma: no cover - platform specific
    values = _proc_kb(Path("/proc/self/status"), ("VmRSS", "VmHWM"))
    return ProcessMemory(values.get("VmRSS"), values.get("VmHWM"), "linux:/proc/self/status")


def _posix_peak_only() -> ProcessMemory:  # pragma: no cover - platform specific
    try:
        import resource
    except ImportError:
        return ProcessMemory(None, None, "unavailable on this platform")
    getrusage = getattr(resource, "getrusage", None)
    rusage_self = getattr(resource, "RUSAGE_SELF", None)
    if getrusage is None or rusage_self is None:
        return ProcessMemory(None, None, "unavailable on this platform")
    peak = getrusage(rusage_self).ru_maxrss
    # ru_maxrss is bytes on macOS and kilobytes on Linux; only macOS gets here.
    return ProcessMemory(None, _mb(peak), "posix:getrusage ru_maxrss (bytes)")


def _proc_kb(path: Path, keys: tuple[str, ...]) -> dict[str, float]:  # pragma: no cover
    """Read ``Key:   1234 kB`` lines out of a procfs file, as megabytes."""
    found: dict[str, float] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in keys:
            try:
                found[key] = float(rest.split()[0]) / 1024.0
            except (IndexError, ValueError):
                continue
    return found


def _mb(value: int | float) -> float:
    return round(float(value) / 1_000_000.0, 1)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def describe_environment() -> dict[str, Any]:
    """What the measurement ran on. Nothing here is a secret."""
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_commit": git_commit(),
    }


def git_commit() -> str | None:
    """The commit the measured code came from, plus ``-dirty`` when uncommitted
    changes were present. ``None`` when git is not available."""
    root = Path(__file__).resolve().parents[4]
    try:
        head = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{head}-dirty" if status else head


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def fingerprint(graph: RoutableGraph) -> dict[str, Any]:
    """A content hash of everything routing reads from a loaded graph.

    Two loaders that agree here built the same graph. ``raw_tags`` is left out
    on purpose: it is provenance kept in the database, and whether a loader
    carries it in memory is exactly the kind of thing this must *not* hide a
    change of routing behaviour behind.
    """
    segment_hash = hashlib.sha256()
    named = 0
    with_raw_tags = 0
    for edge in sorted(graph.segments, key=lambda e: (e.source_u, e.source_v, e.edge_key)):
        feature_values: list[str] = []
        for feature in fields(edge.features):
            if feature.name == "raw_tags":
                if edge.features.raw_tags:
                    with_raw_tags += 1
                continue
            value = getattr(edge.features, feature.name)
            feature_values.append(repr(value.value) if hasattr(value, "value") else repr(value))
        if edge.name is not None:
            named += 1
        # No row id: a segment is identified by its OSM node pair and key, which
        # is what survives re-ingestion. Row ids are fresh per load on the
        # payload path and would make two identical graphs hash differently.
        record = (
            edge.source_u,
            edge.source_v,
            str(edge.edge_key),
            repr(edge.length_m),
            repr(edge.name),
            repr(edge.foot_forward),
            repr(edge.foot_backward),
            edge.geometry.wkb_hex,
            *feature_values,
        )
        segment_hash.update("\x1f".join(record).encode())
        segment_hash.update(b"\n")

    node_hash = hashlib.sha256()
    for node_id, (x, y) in sorted(graph.node_positions.items()):
        node_hash.update(f"{node_id}\x1f{x!r}\x1f{y!r}\n".encode())

    return {
        "nodes": graph.node_count,
        "segments": graph.segment_count,
        "directed_edges": graph.graph.number_of_edges(),
        "named_segments": named,
        "segments_with_raw_tags_in_memory": with_raw_tags,
        "segment_sha256": segment_hash.hexdigest(),
        "node_sha256": node_hash.hexdigest(),
    }


# ---------------------------------------------------------------------------
# Runs and the report
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LoadRun:
    """One load of the graph, with everything needed to judge the number."""

    run: int
    tracemalloc: bool
    started_at: str
    elapsed_seconds: float
    cpu_seconds: float
    #: What `load_graph` itself timed; excludes the harness's own overhead.
    load_seconds_reported: float
    peak_python_heap_mb: float | None
    rss_mb: float | None
    peak_rss_mb: float | None
    available_mb_before: float | None
    available_mb_after: float | None
    memory_pressure: bool
    valid: bool
    invalid_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run,
            "tracemalloc": self.tracemalloc,
            "started_at": self.started_at,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "cpu_seconds": round(self.cpu_seconds, 2),
            "load_seconds_reported": round(self.load_seconds_reported, 2),
            "peak_python_heap_mb": self.peak_python_heap_mb,
            "rss_mb": self.rss_mb,
            "peak_rss_mb": self.peak_rss_mb,
            "available_mb_before": self.available_mb_before,
            "available_mb_after": self.available_mb_after,
            "memory_pressure": self.memory_pressure,
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
        }


def judge_run(
    *,
    elapsed_seconds: float,
    cpu_seconds: float,
    available_mb_before: float | None,
    total_mb: float | None,
) -> tuple[bool, str | None, bool]:
    """Decide whether a run measured the code or the machine.

    Returns ``(valid, reason, memory_pressure)``. Pure, so the rule can be tested
    without loading anything.
    """
    pressure = (
        available_mb_before is not None
        and total_mb is not None
        and total_mb > 0
        and available_mb_before < MEMORY_PRESSURE_FRACTION * total_mb
    )
    if elapsed_seconds > IDLE_RATIO_LIMIT * max(cpu_seconds, 0.001):
        reason = (
            f"wall-clock {elapsed_seconds:.0f} s against {cpu_seconds:.0f} s of CPU: the "
            "process was mostly not running (system suspend or heavy paging)"
        )
        return False, reason, pressure
    return True, None, pressure


@dataclass(slots=True)
class LoadBenchmarkReport:
    region: str
    dataset_id: str
    dataset_checksum: str
    environment: dict[str, Any]
    machine_memory: MachineMemory
    process_memory_method: str
    graph: dict[str, Any] = field(default_factory=dict)
    runs: list[LoadRun] = field(default_factory=list)

    def timing_runs(self) -> list[LoadRun]:
        return [run for run in self.runs if run.valid and not run.tracemalloc]

    def heap_runs(self) -> list[LoadRun]:
        return [
            run for run in self.runs if run.valid and run.tracemalloc and run.peak_python_heap_mb
        ]

    def summary(self) -> dict[str, Any]:
        """Only valid runs count; the invalid ones are listed, not averaged."""
        timing = self.timing_runs()
        heap = self.heap_runs()
        peaks = [run.peak_rss_mb for run in self.runs if run.valid and run.peak_rss_mb is not None]
        elapsed = sorted(run.elapsed_seconds for run in timing)
        return {
            "timing_runs": len(timing),
            "median_seconds": round(statistics.median(elapsed), 2) if elapsed else None,
            "min_seconds": round(elapsed[0], 2) if elapsed else None,
            "max_seconds": round(elapsed[-1], 2) if elapsed else None,
            # max/min. Above ~1.3 the machine, not the code, set the number.
            "spread_ratio": round(elapsed[-1] / elapsed[0], 2) if elapsed and elapsed[0] else None,
            "heap_runs": len(heap),
            "median_peak_python_heap_mb": (
                round(statistics.median(run.peak_python_heap_mb or 0.0 for run in heap), 1)
                if heap
                else None
            ),
            "max_peak_rss_mb": max(peaks) if peaks else None,
            "invalid_runs": sum(1 for run in self.runs if not run.valid),
            "runs_under_memory_pressure": sum(1 for run in self.runs if run.memory_pressure),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "load_benchmark_version": LOAD_BENCHMARK_VERSION,
            "region": self.region,
            "dataset_id": self.dataset_id,
            "dataset_checksum": self.dataset_checksum,
            "environment": self.environment,
            "machine_memory": {
                "total_mb": self.machine_memory.total_mb,
                "method": self.machine_memory.method,
            },
            "process_memory_method": self.process_memory_method,
            "graph": self.graph,
            "summary": self.summary(),
            "runs": [run.to_dict() for run in self.runs],
        }


async def run_load_benchmark(
    session: AsyncSession,
    region_slug: str,
    *,
    runs: int = 3,
    heap_runs: int = 1,
) -> LoadBenchmarkReport:
    """Load a region's active dataset repeatedly and report every attempt.

    Raises :class:`NoActiveDatasetError` when there is nothing to load — a
    benchmark of an empty region would be a number about nothing.
    """
    region = (
        await session.execute(select(PilotRegion).where(PilotRegion.slug == region_slug))
    ).scalar_one_or_none()
    if region is None:
        msg = f"Pilot region {region_slug!r} does not exist."
        raise NoActiveDatasetError(msg)
    dataset = await get_active_dataset(session, region.id)
    if dataset is None:
        msg = f"Region {region_slug!r} has no active network dataset."
        raise NoActiveDatasetError(msg)

    machine = machine_memory()
    report = LoadBenchmarkReport(
        region=region_slug,
        dataset_id=str(dataset.id),
        dataset_checksum=dataset.checksum,
        environment=describe_environment(),
        machine_memory=machine,
        process_memory_method=process_memory().method,
    )

    plan = [False] * max(runs, 0) + [True] * max(heap_runs, 0)
    for index, with_tracemalloc in enumerate(plan, start=1):
        gc.collect()
        before = machine_memory()
        started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        if with_tracemalloc:
            tracemalloc.start()
        cpu_started = time.process_time()
        started = time.perf_counter()
        graph = await load_graph(session, dataset, region_slug)
        elapsed = time.perf_counter() - started
        cpu = time.process_time() - cpu_started
        peak_heap: float | None = None
        if with_tracemalloc:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_heap = _mb(peak)
        process = process_memory()
        after = machine_memory()

        if not report.graph:
            report.graph = fingerprint(graph)

        valid, reason, pressure = judge_run(
            elapsed_seconds=elapsed,
            cpu_seconds=cpu,
            available_mb_before=before.available_mb,
            total_mb=machine.total_mb,
        )
        report.runs.append(
            LoadRun(
                run=index,
                tracemalloc=with_tracemalloc,
                started_at=started_at,
                elapsed_seconds=elapsed,
                cpu_seconds=cpu,
                load_seconds_reported=graph.load_seconds,
                peak_python_heap_mb=peak_heap,
                rss_mb=process.rss_mb,
                peak_rss_mb=process.peak_rss_mb,
                available_mb_before=before.available_mb,
                available_mb_after=after.available_mb,
                memory_pressure=pressure,
                valid=valid,
                invalid_reason=reason,
            )
        )
        del graph

    return report


def render(report: LoadBenchmarkReport) -> list[str]:
    """The human-readable summary, one line per fact."""
    graph = report.graph
    summary = report.summary()
    lines = [
        f"Region     {report.region}",
        f"Dataset    {report.dataset_id}  checksum {report.dataset_checksum[:12]}",
        f"Code       {report.environment.get('git_commit') or 'unknown commit'}",
        f"Machine    {report.environment.get('platform')}  Python {report.environment.get('python')}"
        f"  RAM {_fmt_mb(report.machine_memory.total_mb)}",
        f"Graph      {graph.get('nodes')} nodes · {graph.get('segments')} segments · "
        f"{graph.get('directed_edges')} directed edges · {graph.get('named_segments')} named",
        f"Segments   sha256 {str(graph.get('segment_sha256', ''))[:16]}…   "
        f"nodes sha256 {str(graph.get('node_sha256', ''))[:16]}…",
        "",
        f"{'RUN':<5}{'MODE':<8}{'ELAPSED s':>11}{'CPU s':>9}{'HEAP MB':>10}{'RSS MB':>9}"
        f"{'FREE MB':>10}  STATUS",
    ]
    for run in report.runs:
        status = "ok"
        if not run.valid:
            status = f"INVALID: {run.invalid_reason}"
        elif run.memory_pressure:
            status = "ok, under memory pressure"
        lines.append(
            f"{run.run:<5}{'heap' if run.tracemalloc else 'timing':<8}"
            f"{run.elapsed_seconds:>11.2f}{run.cpu_seconds:>9.1f}"
            f"{_fmt_num(run.peak_python_heap_mb):>10}{_fmt_num(run.rss_mb):>9}"
            f"{_fmt_num(run.available_mb_before):>10}  {status}"
        )
    lines.append("")
    if summary["timing_runs"]:
        lines.append(
            f"Load time  median {summary['median_seconds']} s over {summary['timing_runs']} valid "
            f"timing run(s), min {summary['min_seconds']} s, max {summary['max_seconds']} s, "
            f"spread x{summary['spread_ratio']}"
        )
    else:
        lines.append("Load time  no valid timing run")
    if summary["heap_runs"]:
        lines.append(
            f"Peak heap  {summary['median_peak_python_heap_mb']} MB (tracemalloc, median of "
            f"{summary['heap_runs']} run(s))"
        )
    if summary["max_peak_rss_mb"] is not None:
        lines.append(
            f"Peak RSS   {summary['max_peak_rss_mb']} MB ({report.process_memory_method}; "
            "process-wide, so later runs include earlier ones)"
        )
    if summary["invalid_runs"]:
        lines.append(f"Excluded   {summary['invalid_runs']} invalid run(s), listed above")
    if summary["runs_under_memory_pressure"]:
        lines.append(
            f"Caution    {summary['runs_under_memory_pressure']} run(s) started with under "
            f"{int(MEMORY_PRESSURE_FRACTION * 100)}% of physical memory free; wall-clock from "
            "those measures the machine, not the code"
        )
    return lines


def _fmt_mb(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.0f} MB"


def _fmt_num(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"
