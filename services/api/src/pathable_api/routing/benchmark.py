"""Measuring how fast routing actually is.

Exists so performance claims come from a run somebody can repeat, not from an
estimate. Every number this produces is a wall-clock measurement on the machine
it ran on, and the report says which dataset it measured — a figure from the
nine-node synthetic fixture and a figure from a real city network are not
comparable, and neither should be quoted as the other.
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point

from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.routing.engine import RoutingError, compute_route
from pathable_api.routing.graph import RoutableGraph
from pathable_api.routing.profiles import MobilityProfile


@dataclass(slots=True)
class LatencySummary:
    """Wall-clock milliseconds for one profile over one sample set."""

    profile: str
    samples: int
    failures: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "samples": self.samples,
            "failures": self.failures,
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "mean_ms": round(self.mean_ms, 2),
        }


@dataclass(slots=True)
class BenchmarkReport:
    dataset: str
    node_count: int
    segment_count: int
    summaries: list[LatencySummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "node_count": self.node_count,
            "segment_count": self.segment_count,
            "profiles": [summary.to_dict() for summary in self.summaries],
        }


def measure(
    graph: RoutableGraph,
    profiles: list[MobilityProfile],
    *,
    samples: int = 50,
    seed: int = 20260812,
    dataset_label: str | None = None,
) -> BenchmarkReport:
    """Time route computation over randomly chosen node pairs.

    The same seed produces the same pairs, so two runs are comparable and a
    regression is a real change rather than a different set of journeys.
    """
    # Deterministic by design: the point is that two runs measure the same
    # journeys. Nothing here is a secret.
    rng = random.Random(seed)  # noqa: S311
    node_ids = sorted(graph.node_positions)
    if len(node_ids) < 2:
        msg = "A benchmark needs at least two nodes to route between."
        raise ValueError(msg)

    pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    while len(pairs) < samples:
        origin_id, destination_id = rng.sample(node_ids, 2)
        pairs.append((graph.node_positions[origin_id], graph.node_positions[destination_id]))

    report = BenchmarkReport(
        dataset=dataset_label or f"{graph.region_slug}:{graph.checksum[:12]}",
        node_count=graph.node_count,
        segment_count=graph.segment_count,
    )

    for profile in profiles:
        durations: list[float] = []
        failures = 0
        for origin, destination in pairs:
            started = time.perf_counter()
            try:
                compute_route(graph, origin=origin, destination=destination, profile=profile)
            except RoutingError:
                # A journey with no possible route is a real outcome, not an
                # error to hide — but its timing says nothing about routing
                # speed, so it is counted rather than averaged in.
                failures += 1
                continue
            durations.append((time.perf_counter() - started) * 1000.0)

        report.summaries.append(_summarise(profile.key, durations, failures))

    return report


def _summarise(profile: str, durations: list[float], failures: int) -> LatencySummary:
    if not durations:
        return LatencySummary(profile, 0, failures, 0.0, 0.0, 0.0, 0.0)

    ordered = sorted(durations)
    return LatencySummary(
        profile=profile,
        samples=len(ordered),
        failures=failures,
        p50_ms=statistics.median(ordered),
        p95_ms=ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        max_ms=ordered[-1],
        mean_ms=statistics.fmean(ordered),
    )


def build_measurement_grid(
    size: int, *, origin: tuple[float, float] = (-80.54, 43.47)
) -> NetworkPayload:
    """A regular lattice, for measuring how routing scales.

    **Not a map of anywhere.** It exists purely so latency can be characterised
    against a network of a chosen size when a real one is unavailable, and any
    number derived from it must be reported as what it is.

    Every fourth segment is stairs and every third has no recorded surface, so
    the cost model and the uncertainty penalty are exercised rather than
    measured on a uniform network where every edge costs the same.
    """
    step = 0.0006  # ~50 m north-south
    nodes: list[NetworkNode] = []
    for row in range(size):
        for column in range(size):
            nodes.append(
                NetworkNode(
                    source_node_id=f"n{row}_{column}",
                    geometry=Point(origin[0] + column * step, origin[1] + row * step),
                )
            )

    position = {node.source_node_id: (node.longitude, node.latitude) for node in nodes}
    edges: list[NetworkEdge] = []
    index = 0
    for row in range(size):
        for column in range(size):
            for neighbour_row, neighbour_column in ((row, column + 1), (row + 1, column)):
                if neighbour_row >= size or neighbour_column >= size:
                    continue
                u = f"n{row}_{column}"
                v = f"n{neighbour_row}_{neighbour_column}"
                tags: dict[str, Any] = {"highway": "footway"}
                if index % 4 == 0:
                    tags = {"highway": "steps", "step_count": "12"}
                elif index % 3 == 0:
                    tags = {"highway": "footway"}  # no surface recorded
                else:
                    tags = {"highway": "footway", "surface": "asphalt", "smoothness": "good"}

                edges.append(
                    NetworkEdge(
                        source_u=u,
                        source_v=v,
                        edge_key=0,
                        geometry=LineString([position[u], position[v]]),
                        features=normalise_edge(tags),
                        source_way_id=f"grid-{index}",
                    )
                )
                index += 1

    return NetworkPayload(nodes=nodes, edges=edges)
