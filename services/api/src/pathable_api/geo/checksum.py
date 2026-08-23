"""Deterministic dataset checksums.

A checksum answers "is this the same network?" — so two ingestions of unchanged
upstream data must produce the same value, and any change to geometry, topology
or a routing-relevant attribute must change it.

Determinism requires ordering everything and rounding coordinates: floating-point
noise in the seventh decimal place is roughly 1 cm and is not a real difference,
but it would change a naive hash on every run.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

#: ~1.1 cm at the equator. Fine enough that genuine geometry edits register,
#: coarse enough that re-projection noise does not.
_COORD_PRECISION = 7
_LENGTH_PRECISION = 3


class ChecksumNode(Protocol):
    source_node_id: str
    longitude: float
    latitude: float


class ChecksumEdge(Protocol):
    source_u: str
    source_v: str
    edge_key: int
    length_m: float
    directed: bool

    def checksum_attributes(self) -> Sequence[tuple[str, str]]: ...


def _format_float(value: float, precision: int) -> str:
    return f"{value:.{precision}f}"


def dataset_checksum(
    nodes: Iterable[tuple[str, float, float]],
    edges: Iterable[tuple[str, str, int, float, bool, Sequence[tuple[str, Any]]]],
) -> str:
    """Hash a network's content.

    Nodes contribute identity and position; edges contribute identity, topology,
    length and every routing-relevant attribute. Both are sorted, so insertion
    order — which differs between OSMnx runs — cannot affect the result.
    """
    digest = hashlib.sha256()

    node_lines = sorted(
        f"N|{source_id}|{_format_float(lon, _COORD_PRECISION)}|{_format_float(lat, _COORD_PRECISION)}"
        for source_id, lon, lat in nodes
    )
    for line in node_lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")

    edge_lines = sorted(
        "E|{u}|{v}|{key}|{length}|{directed}|{attributes}".format(
            u=source_u,
            v=source_v,
            key=edge_key,
            length=_format_float(length_m, _LENGTH_PRECISION),
            directed=int(directed),
            attributes=";".join(
                f"{name}={'' if value is None else value}"
                for name, value in sorted(attributes, key=lambda item: item[0])
            ),
        )
        for source_u, source_v, edge_key, length_m, directed, attributes in edges
    )
    for line in edge_lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")

    return digest.hexdigest()
