"""The shadow-routing study, on invented streets and PathAble's own router.

What these protect:

- a City surface describes only the routing segments it covers, never a
  whole way or a whole long segment;
- only City-only rows fill anything: never an OSM surface, a conflict, an
  agreement, a template default or a value routing has no class for;
- the shadow graph changes costs through the production cost model, and the
  baseline graph is left exactly as it was;
- every change lands in the right category, and a moved route is explained
  from its costs.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.enums import SurfaceClass
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.kitchener.osm_extract import OsmNode, OsmWay, StudyExtract
from pathable_api.geo.kitchener.shadow_overlay import (
    CONFLICT_SENSITIVITY,
    NOT_IN_GRAPH,
    CitySurface,
    SegmentSource,
    ShadowError,
    Skip,
    WaySegment,
    load_surface_evidence,
    locate_segments,
    plan_overlay,
    shadow_graph,
    surface_class_of,
    way_vertex_positions,
)
from pathable_api.geo.kitchener.shadow_run import graph_identity
from pathable_api.geo.kitchener.shadow_study import (
    CUSTOM_ROUGH_KEY,
    Category,
    Journey,
    RouteFacts,
    algorithms_agree,
    broad_corpus,
    classify,
    corpus_digest,
    run_pair,
    study_profiles,
    surface_lookup,
)
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.routing.engine import compute_route
from pathable_api.routing.graph import RoutableGraph, graph_from_payload
from pathable_api.routing.profiles import STANDARD, get_profile
from tests.unit.kitchener_streets import Identity

LON, LAT = -80.49, 43.45
FOOTWAY = {"highway": "footway"}


def at(east_m: float, north_m: float) -> tuple[float, float]:
    per_lon = 111_320.0 * math.cos(math.radians(LAT))
    return (LON + east_m / per_lon, LAT + north_m / 111_320.0)


class Net:
    """Invented ways, cut at every node as the PBF import cuts them."""

    def __init__(self) -> None:
        self.nodes: dict[str, tuple[float, float]] = {}
        self.edges: list[NetworkEdge] = []
        self.segments: dict[int, list[WaySegment]] = {}

    def node(self, name: str, east: float, north: float) -> str:
        self.nodes[name] = (east, north)
        return name

    def way(self, way_id: int, names: list[str], tags: dict[str, str] | None = None) -> None:
        features = normalise_edge(dict(tags or FOOTWAY))
        position = 0.0
        found = []
        for key, (u, v) in enumerate(pairwise(names)):
            (x1, y1), (x2, y2) = self.nodes[u], self.nodes[v]
            length = math.hypot(x2 - x1, y2 - y1)
            self.edges.append(
                NetworkEdge(
                    source_u=u,
                    source_v=v,
                    edge_key=key,
                    geometry=LineString([at(x1, y1), at(x2, y2)]),
                    features=features,
                    source_way_id=str(way_id),
                )
            )
            found.append(WaySegment(f"{u}->{v}#{key}", way_id, position, position + length))
            position += length
        self.segments[way_id] = found

    def graph(self) -> RoutableGraph:
        nodes = [NetworkNode(n, Point(*at(*xy))) for n, xy in sorted(self.nodes.items())]
        return graph_from_payload(NetworkPayload(nodes=nodes, edges=self.edges))


def city(
    way: int,
    start: float,
    end: float,
    raw: str = "ASPHALT",
    normalized: str | None = "asphalt",
    relationship: str = "source_only_kitchener",
    record: int = 1,
) -> CitySurface:
    return CitySurface(
        reconciliation_id=f"surface_material/kitchener/{record}/way/{way}",
        record_id=record,
        way_id=way,
        from_m=start,
        to_m=end,
        raw_value=raw,
        normalized_value=normalized,
        surface_class=surface_class_of(normalized),
        relationship=relationship,
        source_capture_date="2012-05-01",
    )


def features_of(graph: RoutableGraph) -> dict[str, Any]:
    return {e.identity: e.features for e in graph.segments}


# ---------------------------------------------------------------------------
# Local scope
# ---------------------------------------------------------------------------


def test_a_short_city_record_cannot_make_a_long_segment_asphalt() -> None:
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 100, 0)
    net.way(1, ["a", "b"])
    item = city(1, 10.0, 20.0)

    plan = plan_overlay([item], net.segments, features_of(net.graph()))

    assert plan.fills == {}
    assert plan.skipped[str(Skip.BELOW_COVERAGE)] == 1
    assert plan.assertion_outcomes[item.reconciliation_id] == str(Skip.BELOW_COVERAGE)


def test_a_city_record_fills_only_the_segments_it_covers_on_a_long_way() -> None:
    net = Net()
    names = [net.node(f"n{i}", 10.0 * i, 0) for i in range(11)]
    net.way(1, names)

    plan = plan_overlay([city(1, 20.0, 40.0)], net.segments, features_of(net.graph()))

    assert sorted(plan.fills) == ["n2->n3#2", "n3->n4#3"]
    assert all(fill.surface_class is SurfaceClass.PAVED for fill in plan.fills.values())


def test_several_city_records_along_one_way_each_fill_their_own_part() -> None:
    net = Net()
    names = [net.node(f"n{i}", 10.0 * i, 0) for i in range(6)]
    net.way(1, names)
    items = [
        city(1, 0.0, 20.0, record=1),
        city(1, 30.0, 50.0, "GRAVEL", "gravel", record=2),
    ]

    plan = plan_overlay(items, net.segments, features_of(net.graph()))

    assert {k: v.surface for k, v in plan.fills.items()} == {
        "n0->n1#0": "asphalt",
        "n1->n2#1": "asphalt",
        "n3->n4#3": "gravel",
        "n4->n5#4": "gravel",
    }


def test_segments_are_placed_by_their_node_index_along_the_way() -> None:
    nodes = {i: OsmNode(i, float(10 * (i - 1)), 0.0, 1, None, {}) for i in (1, 2, 3, 4)}
    extract = StudyExtract(nodes=nodes, ways={7: OsmWay(7, 1, None, {}, (1, 2, 3, 4))})
    positions = way_vertex_positions(extract, Identity())
    sources = [
        SegmentSource("2", "3", 1, "7"),
        SegmentSource("3", "2", 1, "7"),  # wrong way round for key 1
        SegmentSource("1", "2", 0, "8"),  # a way the extract does not hold
    ]

    found, problems = locate_segments(sources, extract, positions)

    assert found == {7: [WaySegment("2->3#1", 7, 10.0, 20.0)]}
    assert problems == {"nodes_do_not_match_the_way": 1, "way_not_in_extract": 1}


def test_an_extent_on_a_way_the_graph_leaves_out_describes_nothing() -> None:
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 50, 0)
    net.way(1, ["a", "b"])
    item = city(99, 0.0, 50.0)

    plan = plan_overlay([item], net.segments, features_of(net.graph()))

    assert plan.assertion_outcomes[item.reconciliation_id] == NOT_IN_GRAPH


# ---------------------------------------------------------------------------
# What may fill, and what never does
# ---------------------------------------------------------------------------


def test_an_osm_surface_is_never_overwritten() -> None:
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 50, 0)
    net.way(1, ["a", "b"], {"highway": "footway", "surface": "concrete"})

    plan = plan_overlay([city(1, 0.0, 50.0)], net.segments, features_of(net.graph()))

    assert plan.fills == {}
    assert plan.skipped[str(Skip.OSM_SURFACE_PRESENT)] == 1


def test_two_city_surfaces_on_one_segment_leave_it_unknown() -> None:
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 100, 0)
    net.way(1, ["a", "b"])
    items = [city(1, 0.0, 60.0, record=1), city(1, 60.0, 100.0, "GRAVEL", "gravel", record=2)]

    plan = plan_overlay(items, net.segments, features_of(net.graph()))

    assert plan.fills == {}
    assert plan.skipped[str(Skip.MIXED_CITY_SURFACES)] == 1


def test_a_value_the_cost_model_has_no_class_for_fills_nothing() -> None:
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 50, 0)
    net.way(1, ["a", "b"])

    plan = plan_overlay(
        [city(1, 0.0, 50.0, "BRICK", "bricks")], net.segments, features_of(net.graph())
    )

    assert plan.fills == {}
    assert plan.skipped[str(Skip.OUTSIDE_ROUTING_VOCABULARY)] == 1


def test_the_conflict_sensitivity_only_touches_segments_osm_describes() -> None:
    net = Net()
    for name, east in (("a", 0), ("b", 50), ("c", 100)):
        net.node(name, east, 0)
    net.way(1, ["a", "b"], {"highway": "footway", "surface": "concrete"})
    net.way(2, ["b", "c"])
    items = [
        city(1, 0.0, 50.0, "BRICK", "paving_stones", "conflict", 1),
        city(2, 0.0, 50.0, relationship="conflict", record=2),
    ]

    plan = plan_overlay(items, net.segments, features_of(net.graph()), policy=CONFLICT_SENSITIVITY)

    assert list(plan.fills) == ["a->b#0"]
    assert plan.fills["a->b#0"].replaces is SurfaceClass.PAVED


def _artifact(folder: Path, *, eligible_count: int = 1) -> tuple[Path, Path]:
    """A miniature PA-GEO-06 artifact: one surface row of every relationship, one curb ramp."""
    folder.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """CREATE TABLE r AS SELECT * FROM (VALUES
            ('s1', 'surface', 'source_only_kitchener', [1::BIGINT], 'way/100', 0.0, 20.0,
             ['kitchener/1#surface_material'], []::VARCHAR[], 'not_applicable'),
            ('s2', 'surface', 'conflict', [2::BIGINT], 'way/101', 0.0, 20.0,
             ['kitchener/2#surface_material'], ['way/101@v3#surface'], 'apparently_independent'),
            ('s3', 'surface', 'agreement', [3::BIGINT], 'way/102', 0.0, 20.0,
             ['kitchener/3#surface_material'], ['way/102@v1#surface'], 'possible_shared_lineage'),
            ('s4', 'surface', 'source_only_osm', [4::BIGINT], 'way/103', 0.0, 20.0,
             []::VARCHAR[], ['way/103@v1#surface'], 'not_applicable'),
            ('s5', 'surface', 'unknown', [5::BIGINT], 'way/104', 0.0, 20.0,
             []::VARCHAR[], []::VARCHAR[], 'not_applicable'),
            ('c1', 'curb_ramp', 'source_only_kitchener', [6::BIGINT], 'node/9', NULL, NULL,
             ['kitchener/6#curb_ramp'], ['node/9@v1#barrier'], 'not_applicable')
            ) AS v(reconciliation_id, topic, semantic_relationship, source_records,
                   target_element, from_m, to_m, kitchener_assertions, osm_assertions,
                   lineage_relationship)"""
        )
        connection.execute(
            """CREATE TABLE a AS SELECT * FROM (VALUES
            ('kitchener/1#surface_material', 'ASPHALT', 'asphalt', 'orthoimagery', '2012-05-01',
             2021::BIGINT, NULL, NULL),
            ('kitchener/2#surface_material', 'BRICK', 'bricks', 'orthoimagery', NULL, NULL,
             NULL, NULL),
            ('way/101@v3#surface', 'concrete', 'concrete', NULL, NULL, NULL, '2021-03-25',
             '2021-03-25T00:00:00Z')
            ) AS v(assertion_id, raw_value, normalized_value, capture_source,
                   source_capture_date, inspection_year, observation_date, osm_value_since)"""
        )
        for table, name in (("r", "reconciliations"), ("a", "assertions")):
            connection.execute(f"COPY {table} TO '{(folder / name).as_posix()}.parquet'")
    finally:
        connection.close()
    from pathable_api.geo.overture.evidence import file_sha256

    files = {
        name: {"file": f"{name}.parquet", "sha256": file_sha256(folder / f"{name}.parquet")}
        for name in ("reconciliations", "assertions")
    }
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_version": "kitchener-geo06-artifact-v1",
                "versions": {"reconciliation_policy": "kitchener-geo06-reconciliation-v1"},
                "files": files,
                "content_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    committed = folder / "evidence.json"
    committed.write_text(
        json.dumps(
            {
                "artifact": {"files": files},
                "outcomes": {
                    "surface": {"semantic_relationship": {"source_only_kitchener": eligible_count}}
                },
                "content_sha256": "e" * 64,
            }
        ),
        encoding="utf-8",
    )
    return folder, committed


def test_only_city_only_surface_rows_are_eligible(tmp_path: Path) -> None:
    folder, committed = _artifact(tmp_path)

    found = load_surface_evidence(folder, committed)

    assert [i.reconciliation_id for i in found.eligible] == ["s1"]
    assert found.eligible[0].surface_class is SurfaceClass.PAVED
    assert found.eligible[0].freshness == "capture_dated_only"
    # Conflicts are kept apart for the sensitivity, never mixed into the policy.
    assert [i.reconciliation_id for i in found.conflicts] == ["s2"]
    assert found.conflicts[0].osm_value == "concrete"
    assert found.relationships == {
        "agreement": 1,
        "conflict": 1,
        "source_only_kitchener": 1,
        "source_only_osm": 1,
        "unknown": 1,
    }


def test_an_artifact_the_committed_evidence_does_not_describe_is_refused(tmp_path: Path) -> None:
    folder, committed = _artifact(tmp_path)
    document = json.loads(committed.read_text("utf-8"))
    document["artifact"]["files"]["assertions"]["sha256"] = "0" * 64
    committed.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ShadowError, match="committed evidence"):
        load_surface_evidence(folder, committed)


def test_a_city_only_count_that_disagrees_with_the_evidence_is_refused(tmp_path: Path) -> None:
    folder, committed = _artifact(tmp_path, eligible_count=943)

    with pytest.raises(ShadowError, match="count"):
        load_surface_evidence(folder, committed)


# ---------------------------------------------------------------------------
# The router, on both graphs
# ---------------------------------------------------------------------------


def _fork(tags_short: dict[str, str] | None = None) -> Net:
    """Two ways from a to b: a straight 100 m, and a 115 m dog-leg through m."""
    net = Net()
    net.node("a", 0, 0)
    net.node("b", 100, 0)
    net.node("m", 50, 28.4)
    net.way(1, ["a", "b"], tags_short)
    net.way(2, ["a", "m", "b"])
    return net


def _journey(net: Net) -> Journey:
    return Journey("T000", "test", at(*net.nodes["a"]), at(*net.nodes["b"]))


def _run(net: Net, items: list[CitySurface], profile_key: str) -> Any:
    graph = net.graph()
    plan = plan_overlay(items, net.segments, features_of(graph))
    shadow = shadow_graph(graph, plan)
    profile = next(p for p in study_profiles() if p.key == profile_key)
    result, _pair = run_pair(
        _journey(net),
        profile,
        graph,
        shadow,
        plan.fills,
        (surface_lookup(graph), surface_lookup(shadow)),
    )
    return result


def test_municipal_asphalt_on_the_longer_way_moves_the_wheelchair_route() -> None:
    net = _fork()

    result = _run(net, [city(2, 0.0, 115.0)], "wheelchair")

    assert result.category is Category.ROUTE_CHANGED
    assert result.base.path == ("a->b#0",)
    assert result.shadow.path == ("a->m#0", "m->b#1")
    assert result.cause is not None
    # Explained from the costs: the unknown-surface penalty on the dog-leg is gone.
    assert (
        result.cause["route_b_shadow"]["cost_shadow"]
        < result.cause["route_a_baseline"]["cost_baseline"]
    )
    assert "lower its cost" in result.cause["cause"]


def test_the_shortest_distance_route_never_moves() -> None:
    net = _fork()

    result = _run(net, [city(2, 0.0, 115.0)], "standard")

    assert result.base.path == result.shadow.path == ("a->b#0",)
    assert result.category is Category.NOT_EXPOSED


def test_municipal_gravel_is_a_hard_change_only_for_a_declared_requirement() -> None:
    net = _fork()
    gravel = [city(1, 0.0, 100.0, "GRAVEL", "gravel")]

    custom = _run(net, gravel, CUSTOM_ROUGH_KEY)
    wheelchair = _run(net, gravel, "wheelchair")

    assert custom.category is Category.FEASIBILITY_CHANGED
    assert custom.blocked == ("a->b#0",)
    # No preset excludes a rough surface: for them it is a cost, and the route moves by weight.
    assert wheelchair.category is Category.ROUTE_CHANGED
    assert wheelchair.blocked == ()


def test_municipal_asphalt_on_the_chosen_path_changes_only_its_cost() -> None:
    net = _fork()

    result = _run(net, [city(1, 0.0, 100.0)], "wheelchair")

    assert result.category is Category.COST_ONLY
    assert result.shadow.effective_m < result.base.effective_m
    assert result.shadow.overlay_by_class["paved"] == pytest.approx(100.0, rel=0.01)


def test_the_baseline_graph_is_untouched_and_routes_as_before() -> None:
    net = _fork()
    graph = net.graph()
    before = graph_identity(graph)
    journey = _journey(net)
    wheelchair = get_profile("wheelchair")
    first = compute_route(
        graph, origin=journey.origin, destination=journey.destination, profile=wheelchair
    )
    plan = plan_overlay([city(2, 0.0, 115.0)], net.segments, features_of(graph))
    shadow = shadow_graph(graph, plan)
    compute_route(
        shadow, origin=journey.origin, destination=journey.destination, profile=wheelchair
    )

    again = compute_route(
        graph, origin=journey.origin, destination=journey.destination, profile=wheelchair
    )

    assert graph_identity(graph) == before
    assert graph_identity(shadow) != before
    assert [s.edge_identity for s in again.segments] == [s.edge_identity for s in first.segments]
    assert again.effective_distance_m == first.effective_distance_m


def test_dijkstra_and_a_star_agree_on_the_shadow_graph() -> None:
    net = _fork()
    graph = net.graph()
    shadow = shadow_graph(
        graph, plan_overlay([city(2, 0.0, 115.0)], net.segments, features_of(graph))
    )

    for profile in study_profiles():
        assert algorithms_agree(shadow, _journey(net), profile)["agree"]


# ---------------------------------------------------------------------------
# Categories and corpora
# ---------------------------------------------------------------------------


def _facts(**values: Any) -> RouteFacts:
    return RouteFacts(**{"exists": True, "path": ("x",), **values})


@pytest.mark.parametrize(
    ("base", "shadow", "blocked", "expected"),
    [
        (_facts(), _facts(exists=False, path=()), False, Category.FEASIBILITY_CHANGED),
        (_facts(), _facts(), True, Category.FEASIBILITY_CHANGED),
        (_facts(), _facts(path=("y",)), False, Category.ROUTE_CHANGED),
        (_facts(effective_m=10.0), _facts(effective_m=9.0), False, Category.COST_ONLY),
        (
            _facts(explanation_digest="a"),
            _facts(explanation_digest="b"),
            False,
            Category.EVIDENCE_ONLY,
        ),
        (_facts(overlay_m=5.0), _facts(overlay_m=5.0), False, Category.NO_EFFECT),
        (_facts(), _facts(), False, Category.NOT_EXPOSED),
        (_facts(exists=False), _facts(exists=False), False, Category.NO_ROUTE_EITHER),
    ],
)
def test_each_change_lands_in_one_category(
    base: RouteFacts, shadow: RouteFacts, blocked: bool, expected: Category
) -> None:
    assert classify(base, shadow, blocked=blocked) is expected


def test_the_broad_corpus_is_the_same_for_the_same_seed() -> None:
    net = Net()
    for i in range(12):
        net.node(f"g{i}", 400.0 * (i % 4), 400.0 * (i // 4))
    for i in range(12):
        if i % 4 != 3:
            net.way(100 + i, [f"g{i}", f"g{i + 1}"])
        if i < 8:
            net.way(200 + i, [f"g{i}", f"g{i + 4}"])
    graph = net.graph()
    west, south = at(-10, -10)
    east, north = at(1300, 900)

    def draw(seed: str) -> list[Journey]:
        return broad_corpus(graph, size=5, seed=seed, bounds=(west, south, east, north))

    first, second = draw("s"), draw("s")

    assert first == second
    assert corpus_digest(first) == corpus_digest(second)
    assert len(first) == 5
    assert all(j.corpus == "broad" for j in first)


def test_the_standard_profile_has_no_surface_rule() -> None:
    # The premise of "the shortest route never moves": if this changes, so must the study.
    assert STANDARD.surface_penalty == {}
    assert not STANDARD.hard_limits.exclude_rough_surface
