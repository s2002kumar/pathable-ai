"""Import a real pedestrian network from OpenStreetMap.

OSMnx handles the Overpass query and the topology cleanup; everything that
matters to accessibility happens afterwards, in :mod:`pathable_api.geo.features`,
so an OSM import and the synthetic fixture produce structurally identical
networks and are validated by exactly the same code.

Two things are deliberate here:

* **Extra tags are requested explicitly.** OSMnx's default tag set is tuned for
  vehicle routing and drops ``surface``, ``smoothness``, ``incline``, ``kerb``
  and the rest. Without this configuration every accessibility attribute would
  come back unknown — and it would look like sparse OSM coverage rather than our
  own query throwing the data away.
* **Requests are cached and rate-limited.** Overpass is a donated public service.
  Re-running an import during development must not re-query it.
"""

from __future__ import annotations

import datetime as dt
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import osmnx as ox
from networkx import MultiDiGraph, MultiGraph
from shapely.geometry import LineString, Point

from pathable_api.core.logging import get_logger
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload

logger = get_logger(__name__)

#: Way tags PathAble needs on top of OSMnx's defaults. Ordered so the resulting
#: ingestion configuration is stable between runs and diffs cleanly.
ACCESSIBILITY_WAY_TAGS: tuple[str, ...] = (
    "access",
    "crossing",
    "crossing:markings",
    "curb",
    "foot",
    "footway",
    "handrail",
    "incline",
    "indoor",
    "kerb",
    "lit",
    "ramp",
    "sidewalk",
    "smoothness",
    "step_count",
    "surface",
    "tactile_paving",
    "wheelchair",
    "width",
)

#: Node tags that matter at junctions — a dropped kerb is mapped on the node.
ACCESSIBILITY_NODE_TAGS: tuple[str, ...] = (
    "barrier",
    "crossing",
    "highway",
    "kerb",
    "tactile_paving",
    "traffic_signals",
    "wheelchair",
)

#: Identifies PathAble to Overpass operators so they can contact us if an import
#: misbehaves, which is the minimum courtesy for using a donated service.
USER_AGENT = (
    "PathAble/0.1 (accessibility routing pilot; +https://github.com/s2002kumar/pathable-ai)"
)


#: Overpass endpoints to try, in order of preference. All are free, public, and
#: operated by the OpenStreetMap community — no key, no account, no cost.
#:
#: ``overpass-api.de`` is the canonical name and round-robins across several
#: backend machines. ``z.`` and ``lz4.`` name individual backends. Both forms are
#: listed because of the failure mode documented at
#: :func:`select_overpass_endpoint`.
OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api",
    "https://z.overpass-api.de/api",
    "https://lz4.overpass-api.de/api",
)

#: How long to wait for a TCP handshake when probing an endpoint. Short: this is
#: a reachability question, not a request.
_PROBE_TIMEOUT_SECONDS = 4.0


class OverpassUnreachableError(RuntimeError):
    """Raised when no configured Overpass endpoint can be reached."""


@dataclass(frozen=True, slots=True)
class OsmImport:
    payload: NetworkPayload
    #: Everything needed to reproduce this import.
    configuration: dict[str, Any]
    retrieved_at: dt.datetime


def select_overpass_endpoint(
    candidates: Sequence[str] = OVERPASS_ENDPOINTS,
    *,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> str:
    """Choose an Overpass endpoint that is actually reachable from this host.

    This exists because of a specific and expensive failure. OSMnx pins the
    Overpass hostname to one IP address for the duration of an import — it calls
    ``socket.gethostbyname`` once and patches ``getaddrinfo`` to return that
    address — so that its rate-limit accounting and its query hit the same
    backend. That is correct behaviour for slot management, but it means a
    round-robin name with one unreachable member is a coin flip, and losing the
    flip hangs the whole import until the request timeout rather than failing
    over.

    Observed here: ``overpass-api.de`` resolved to ``162.55.144.139`` (reachable)
    and ``65.109.112.52`` (not reachable from this network). Imports that pinned
    the second address stalled indefinitely.

    So an endpoint is only accepted if *every* address it resolves to accepts a
    connection — whichever one OSMnx pins, the import will work.
    """
    failures: list[str] = []

    for endpoint in candidates:
        hostname = urlsplit(endpoint).hostname
        if hostname is None:
            failures.append(f"{endpoint}: no hostname")
            continue

        try:
            addresses = sorted(
                {
                    str(info[4][0])
                    for info in socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
                }
            )
        except OSError as error:
            failures.append(f"{hostname}: DNS lookup failed ({error.strerror or error})")
            continue

        unreachable = [
            address for address in addresses if not _accepts_connections(address, timeout)
        ]
        if unreachable:
            failures.append(f"{hostname}: no response from {', '.join(unreachable)}")
            continue

        logger.info(
            "Selected Overpass endpoint",
            extra={"endpoint": endpoint, "addresses": addresses},
        )
        return endpoint

    msg = "No Overpass endpoint is reachable. Tried: " + "; ".join(failures)
    raise OverpassUnreachableError(msg)


def _accepts_connections(address: str, timeout: float) -> bool:
    try:
        with socket.create_connection((address, 443), timeout=timeout):
            return True
    except OSError:
        return False


def configure_osmnx(cache_dir: Path | None = None, *, overpass_url: str | None = None) -> None:
    """Apply PathAble's OSMnx settings. Idempotent."""
    ox.settings.useful_tags_way = sorted({*ox.settings.useful_tags_way, *ACCESSIBILITY_WAY_TAGS})
    ox.settings.useful_tags_node = sorted({*ox.settings.useful_tags_node, *ACCESSIBILITY_NODE_TAGS})
    ox.settings.use_cache = True
    ox.settings.overpass_rate_limit = True
    ox.settings.requests_timeout = 300
    ox.settings.log_console = False
    ox.settings.http_user_agent = USER_AGENT
    # Use the system resolver rather than OSMnx's DNS-over-HTTPS lookup: DoH adds
    # a second name-resolution path with its own failure modes, and PathAble
    # already chooses the endpoint deliberately in `select_overpass_endpoint`.
    ox.settings.doh_url_template = None
    ox.settings.overpass_url = overpass_url or select_overpass_endpoint()
    if cache_dir is not None:
        ox.settings.cache_folder = str(cache_dir)


def download_walk_network(
    bounds: tuple[float, float, float, float],
    *,
    cache_dir: Path | None = None,
    simplify: bool = True,
    overpass_url: str | None = None,
) -> MultiDiGraph[int]:
    """Fetch the walkable network inside ``(min_lon, min_lat, max_lon, max_lat)``.

    ``network_type="walk"`` is what makes this a pedestrian network rather than a
    road network: OSMnx excludes motorways and includes footpaths, steps and
    crossings, and treats every way as bidirectional because pedestrian travel
    ignores vehicle one-way restrictions.
    """
    configure_osmnx(cache_dir, overpass_url=overpass_url)
    logger.info("Requesting OSM walk network", extra={"bounds": list(bounds)})
    graph: MultiDiGraph[int] = ox.graph.graph_from_bbox(
        bbox=bounds,
        network_type="walk",
        simplify=simplify,
        # Keep every component. Discarding the smaller ones would silently delete
        # real footpaths that happen not to connect to the largest island, and
        # "no route found" is a more honest answer than a route that ignores them.
        retain_all=True,
        truncate_by_edge=True,
    )
    return graph


def graph_to_payload(graph: MultiDiGraph[int]) -> NetworkPayload:
    """Convert an OSMnx graph into PathAble's source-neutral network payload.

    The graph is collapsed to undirected first. OSMnx models a two-way footway as
    two directed edges; keeping both would double the edge count and make the
    dataset checksum depend on OSMnx's internal direction bookkeeping rather than
    on the network itself.
    """
    undirected: MultiGraph[int] = ox.convert.to_undirected(graph)

    nodes: list[NetworkNode] = []
    for node_id, data in undirected.nodes(data=True):
        nodes.append(
            NetworkNode(
                source_node_id=str(node_id),
                geometry=Point(float(data["x"]), float(data["y"])),
                raw_tags=_clean_tags(data, drop={"x", "y", "street_count"}),
            )
        )

    edges: list[NetworkEdge] = []
    for u, v, key, data in undirected.edges(keys=True, data=True):
        geometry = data.get("geometry")
        if not isinstance(geometry, LineString):
            # Unsimplified straight segments carry no geometry of their own.
            geometry = LineString(
                [
                    (undirected.nodes[u]["x"], undirected.nodes[u]["y"]),
                    (undirected.nodes[v]["x"], undirected.nodes[v]["y"]),
                ]
            )

        tags = _clean_tags(data, drop={"geometry", "length", "osmid", "reversed", "oneway"})
        edges.append(
            NetworkEdge(
                source_u=str(u),
                source_v=str(v),
                edge_key=int(key),
                geometry=geometry,
                features=normalise_edge(tags),
                source_way_id=_first_osmid(data.get("osmid")),
                # OSMnx's walk network is bidirectional by construction: vehicle
                # one-way restrictions do not apply to people on foot.
                directed=False,
                length_m=_positive_length(data.get("length")),
            )
        )

    return NetworkPayload(nodes=nodes, edges=edges)


def import_walk_network(
    bounds: tuple[float, float, float, float],
    *,
    region_slug: str,
    cache_dir: Path | None = None,
    simplify: bool = True,
    overpass_url: str | None = None,
) -> OsmImport:
    """Download and convert a walkable network, recording how it was obtained."""
    retrieved_at = dt.datetime.now(tz=dt.UTC)
    graph = download_walk_network(
        bounds, cache_dir=cache_dir, simplify=simplify, overpass_url=overpass_url
    )
    payload = graph_to_payload(graph)

    logger.info(
        "OSM walk network imported",
        extra={
            "region": region_slug,
            "node_count": payload.node_count,
            "edge_count": payload.edge_count,
        },
    )

    return OsmImport(
        payload=payload,
        configuration={
            "source": "openstreetmap",
            "provider": "overpass-api via osmnx",
            "osmnx_version": ox.__version__,
            "overpass_endpoint": str(ox.settings.overpass_url),
            "region": region_slug,
            "bbox": list(bounds),
            "network_type": "walk",
            "simplify": simplify,
            "retain_all": True,
            "truncate_by_edge": True,
            "requested_way_tags": list(ACCESSIBILITY_WAY_TAGS),
            "requested_node_tags": list(ACCESSIBILITY_NODE_TAGS),
            # ODbL requires attribution wherever this data is shown.
            "attribution": "© OpenStreetMap contributors, ODbL 1.0",
        },
        retrieved_at=retrieved_at,
    )


def _clean_tags(data: dict[str, Any], drop: set[str]) -> dict[str, Any]:
    """Keep the source's own words, minus OSMnx's internal bookkeeping."""
    return {key: value for key, value in data.items() if key not in drop and value is not None}


def _first_osmid(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return str(raw[0]) if raw else None
    return str(raw)


def _positive_length(raw: Any) -> float | None:
    """OSMnx's projected length, when it is usable.

    Preferring it over recomputing keeps our lengths identical to the ones the
    upstream library reports, so two equivalent imports agree on the checksum.
    """
    try:
        length = float(raw)
    except (TypeError, ValueError):
        return None
    return length if length > 0 else None
