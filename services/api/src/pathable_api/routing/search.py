"""Shortest-path search: Dijkstra and A*, over one adjacency.

Two algorithms, one graph, one cost function. Dijkstra is the correctness
baseline — it expands in order of true cost and cannot be fooled by a bad
heuristic. A* is the same search with a lower bound added to the priority, so
proving they agree on cost is a real check on the heuristic rather than a
formality.

**Why the heuristic is admissible.** The estimate is the geodesic distance to
the goal in metres. Every cost this router produces is at least the segment's
real length — accessibility contributions are all non-negative — so straight-
line distance can never exceed the true remaining cost, and A* stays optimal.
That property is exactly what breaks the moment somebody adds a "discount" to
the cost model, which is why `test_astar_matches_dijkstra` exists.

Search runs over an *adjacency callable* rather than the NetworkX graph
directly, so a request that snapped into the middle of a segment can supply
extra edges without mutating a graph shared by other requests.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathable_api.routing.graph import DirectedEdge

#: Neighbours of a node: (destination node, the directed edge that reaches it).
Adjacency = Callable[[str], Iterable[tuple[str, "DirectedEdge"]]]
#: What one directed edge costs. `inf` means impassable.
EdgeWeight = Callable[["DirectedEdge"], float]
#: A lower bound on the remaining cost from a node to the goal.
Heuristic = Callable[[str], float]


class Algorithm(StrEnum):
    DIJKSTRA = "dijkstra"
    ASTAR = "astar"


class SearchLimitError(RuntimeError):
    """The search hit its expansion ceiling before reaching the goal."""


class NoPathError(RuntimeError):
    """No path exists under the current costs."""


@dataclass(slots=True)
class SearchResult:
    """A found path and what it took to find it."""

    cost: float
    nodes: list[str]
    edges: list[DirectedEdge]
    #: How many nodes were settled. The honest measure of search work, and the
    #: number that shows whether A* actually helped.
    expanded: int
    algorithm: Algorithm


@dataclass(slots=True)
class _Frontier:
    """Priority queue with lazy deletion.

    `heapq` has no decrease-key, so a node can be pushed several times at
    improving costs. Stale entries are skipped on pop by comparing against the
    best known cost, which is cheaper than maintaining an indexed heap.
    """

    heap: list[tuple[float, int, str]] = field(default_factory=list)
    counter: int = 0

    def push(self, priority: float, node: str) -> None:
        # The counter breaks ties deterministically, so two runs over the same
        # graph settle nodes in the same order and produce the same path when
        # several are genuinely equal-cost.
        heapq.heappush(self.heap, (priority, self.counter, node))
        self.counter += 1

    def pop(self) -> tuple[float, str]:
        priority, _, node = heapq.heappop(self.heap)
        return priority, node

    def __bool__(self) -> bool:
        return bool(self.heap)


def search(
    start: str,
    goal: str,
    *,
    neighbours: Adjacency,
    weight: EdgeWeight,
    heuristic: Heuristic | None = None,
    algorithm: Algorithm = Algorithm.DIJKSTRA,
    max_expansions: int = 750_000,
) -> SearchResult:
    """Find the cheapest path from ``start`` to ``goal``.

    With ``algorithm=DIJKSTRA`` the heuristic is ignored entirely, which is what
    makes it a baseline: nothing about the estimate can affect the answer.
    """
    use_heuristic = algorithm is Algorithm.ASTAR and heuristic is not None
    estimate: Heuristic = heuristic if use_heuristic and heuristic else _zero

    if start == goal:
        return SearchResult(0.0, [start], [], 0, algorithm)

    best: dict[str, float] = {start: 0.0}
    came_from: dict[str, tuple[str, DirectedEdge]] = {}
    settled: set[str] = set()
    frontier = _Frontier()
    frontier.push(estimate(start), start)
    expanded = 0

    while frontier:
        _, node = frontier.pop()
        if node in settled:
            continue
        settled.add(node)
        expanded += 1

        if node == goal:
            return _reconstruct(start, goal, came_from, best[goal], expanded, algorithm)

        if expanded > max_expansions:
            msg = (
                f"Route search settled more than {max_expansions} nodes without reaching "
                f"the destination. Try a shorter journey."
            )
            raise SearchLimitError(msg)

        node_cost = best[node]
        for neighbour, edge in neighbours(node):
            if neighbour in settled:
                continue
            step = weight(edge)
            if step == float("inf"):
                # A hard constraint. Not a large number — a large number could be
                # outbid by a long enough detour.
                continue
            candidate = node_cost + step
            if candidate < best.get(neighbour, float("inf")):
                best[neighbour] = candidate
                came_from[neighbour] = (node, edge)
                frontier.push(candidate + estimate(neighbour), neighbour)

    raise NoPathError(f"No path from {start} to {goal}.")


def _reconstruct(
    start: str,
    goal: str,
    came_from: dict[str, tuple[str, DirectedEdge]],
    cost: float,
    expanded: int,
    algorithm: Algorithm,
) -> SearchResult:
    nodes = [goal]
    edges: list[DirectedEdge] = []
    node = goal
    while node != start:
        previous, edge = came_from[node]
        edges.append(edge)
        nodes.append(previous)
        node = previous
    nodes.reverse()
    edges.reverse()
    return SearchResult(cost=cost, nodes=nodes, edges=edges, expanded=expanded, algorithm=algorithm)


def _zero(_node: str) -> float:
    return 0.0
