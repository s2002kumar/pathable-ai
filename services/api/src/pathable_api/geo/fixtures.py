"""A small, deterministic synthetic network.

This exists so routing, cost policy and the comparison UI can be developed and
tested without depending on a live Overpass server — tests that hit the internet
are neither deterministic nor polite.

**This is not Waterloo accessibility data.** The geometry sits inside the pilot
bounding box so it renders on the same basemap, but every attribute is invented
for testing. It is loaded under the region slug ``waterloo-synthetic`` and the
source type ``synthetic`` precisely so it can never be mistaken for a survey, and
nothing in the product may present it as one.

The topology is designed around one comparison:

    shortest:   A → B → C → D    — crosses a 14-step stairway and an unmarked
                                   crossing whose kerb nobody has recorded
    step-free:  A → B → F → C → E → D — longer, but no steps, gentle grades and
                                   a signalised crossing with a lowered kerb

with additional segments covering the cases the cost model has to handle:
rough surface, a steep grade, wholly untagged geometry, a one-way passage and an
explicitly foot-prohibited shortcut.
"""

from __future__ import annotations

from typing import Any, Final

from shapely.geometry import LineString, Point
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import IngestionResult, ingest_network
from pathable_api.geo.enums import SourceType
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.geo.regions import WATERLOO_SYNTHETIC, seed_region

#: Kept distinct from the real ``waterloo`` region so a synthetic dataset can
#: never become the active network for the real pilot region.
SYNTHETIC_REGION_SLUG: Final = "waterloo-synthetic"
SYNTHETIC_SOURCE_NAME: Final = "pathable-synthetic-fixture-v1"

#: (longitude, latitude). Inside the Waterloo pilot extent so the fixture renders
#: against the same basemap; the coordinates are otherwise arbitrary.
NODES: Final[dict[str, tuple[float, float]]] = {
    "A": (-80.54000, 43.47000),  # origin
    "B": (-80.53800, 43.47000),
    "C": (-80.53600, 43.47000),
    "D": (-80.53400, 43.47000),  # destination
    "E": (-80.53500, 43.47100),  # signalised crossing, north
    "F": (-80.53700, 43.46900),  # ramp bypassing the stairs, south
    "G": (-80.53900, 43.46850),  # gravel path, south-west
    "U": (-80.53900, 43.47100),  # wholly untagged geometry, north-west
    "H": (-80.54100, 43.47000),  # reachable only via a one-way passage
}

#: (u, v, directed, tags). Tags are written the way OpenStreetMap writes them and
#: pushed through the real normaliser, so the fixture exercises the same code
#: path an OSM import does — including the absences.
EDGES: Final[tuple[tuple[str, str, bool, dict[str, Any]], ...]] = (
    # --- The direct corridor ---------------------------------------------
    (
        "A",
        "B",
        False,
        {
            "highway": "footway",
            "surface": "asphalt",
            "smoothness": "good",
            "lit": "yes",
            "incline": "0%",
            "width": "2.5",
        },
    ),
    # The barrier the whole product exists to route around.
    (
        "B",
        "C",
        False,
        {
            "highway": "steps",
            "step_count": "14",
            "surface": "concrete",
            "handrail": "yes",
            "smoothness": "good",
            "lit": "yes",
        },
    ),
    # Accessible-looking but nobody has recorded the kerb: the canonical
    # "unknown is not yes" case.
    (
        "C",
        "D",
        False,
        {"highway": "footway", "footway": "crossing", "crossing": "unmarked", "surface": "asphalt"},
    ),
    # --- The step-free bypass --------------------------------------------
    (
        "B",
        "F",
        False,
        {
            "highway": "footway",
            "surface": "concrete",
            "smoothness": "good",
            "incline": "4%",
            "lit": "yes",
            "width": "2.0",
        },
    ),
    (
        "F",
        "C",
        False,
        {
            "highway": "footway",
            "surface": "concrete",
            "smoothness": "good",
            "incline": "-4%",
            "lit": "yes",
            "width": "2.0",
        },
    ),
    (
        "C",
        "E",
        False,
        {
            "highway": "footway",
            "footway": "crossing",
            "crossing": "traffic_signals",
            "kerb": "lowered",
            "surface": "asphalt",
            "smoothness": "excellent",
            "tactile_paving": "yes",
            "lit": "yes",
        },
    ),
    (
        "E",
        "D",
        False,
        {
            "highway": "footway",
            "surface": "asphalt",
            "smoothness": "good",
            "incline": "0%",
            "lit": "yes",
            "width": "3.0",
        },
    ),
    # --- Rough and steep --------------------------------------------------
    (
        "A",
        "G",
        False,
        {"highway": "path", "surface": "gravel", "smoothness": "bad", "incline": "2%"},
    ),
    (
        "G",
        "B",
        False,
        {"highway": "path", "surface": "gravel", "smoothness": "very_bad", "incline": "12%"},
    ),
    # --- Wholly untagged: every derived attribute must come out unknown ---
    ("A", "U", False, {}),
    ("U", "B", False, {}),
    # --- One-way passage: H is reachable, but you cannot walk back out ----
    (
        "H",
        "A",
        True,
        {"highway": "footway", "oneway": "yes", "surface": "paving_stones", "smoothness": "good"},
    ),
    # --- Explicitly prohibited: no profile may ever use this --------------
    (
        "B",
        "E",
        False,
        {"highway": "service", "foot": "no", "access": "private", "surface": "asphalt"},
    ),
)


def build_synthetic_network() -> NetworkPayload:
    """Build the fixture. Pure and deterministic — same output every call."""
    nodes = [
        NetworkNode(source_node_id=name, geometry=Point(lon, lat))
        for name, (lon, lat) in NODES.items()
    ]

    edges = []
    for index, (u, v, directed, tags) in enumerate(EDGES):
        edges.append(
            NetworkEdge(
                source_u=u,
                source_v=v,
                edge_key=0,
                geometry=LineString([NODES[u], NODES[v]]),
                features=normalise_edge(tags),
                source_way_id=f"synthetic-{index:03d}",
                directed=directed,
            )
        )

    return NetworkPayload(nodes=nodes, edges=edges)


async def load_synthetic_dataset(
    session: AsyncSession, *, activate: bool = True
) -> IngestionResult:
    """Seed the synthetic region and ingest the fixture as a dataset version.

    Runs the same create → validate → checksum → activate path as a real import,
    which is the point: if the lifecycle breaks, the fixture loader breaks with
    it rather than quietly taking a shortcut past the gate.
    """
    region = await seed_region(session, WATERLOO_SYNTHETIC)
    payload = build_synthetic_network()

    return await ingest_network(
        session,
        region=region,
        payload=payload,
        source_type=SourceType.SYNTHETIC,
        source_name=SYNTHETIC_SOURCE_NAME,
        ingestion_configuration={
            "generator": "pathable_api.geo.fixtures.build_synthetic_network",
            "node_count": payload.node_count,
            "edge_count": payload.edge_count,
            "warning": "Invented data for testing. Not a survey of Waterloo.",
        },
        declared_bounds=WATERLOO_SYNTHETIC.bounds,
        activate=activate,
    )
