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
import uuid
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from pathable_api.geo.enums import SurfaceClass
from pathable_api.geo.features import normalise_edge
from pathable_api.geo.kitchener.osm_extract import OsmNode, OsmWay, StudyExtract
from pathable_api.geo.kitchener.shadow_overlay import (
    CONFLICT_SENSITIVITY,
    NOT_IN_GRAPH,
    CitySurface,
    Fill,
    OverlayPlan,
    SegmentSource,
    ShadowError,
    Skip,
    SurfaceEvidence,
    WaySegment,
    load_surface_evidence,
    locate_segments,
    plan_overlay,
    shadow_graph,
    surface_class_of,
    way_vertex_positions,
)
from pathable_api.geo.kitchener.shadow_page import WATERMARK, render_changes
from pathable_api.geo.kitchener.shadow_run import (
    ActiveDataset,
    StudyOutput,
    changed_routes,
    graph_identity,
    may_move,
    run_study,
    shadow_evidence,
    validation_queue,
)
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
from tests.unit.kitchener_geo06_artifact import write_geo06_artifact
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


def test_only_city_only_surface_rows_are_eligible(tmp_path: Path) -> None:
    folder, committed = write_geo06_artifact(tmp_path)

    found = load_surface_evidence(folder, committed)

    assert [i.reconciliation_id for i in found.eligible] == ["s1"]
    assert found.eligible[0].surface_class is SurfaceClass.PAVED
    assert found.eligible[0].freshness == "capture_dated_only"
    # Conflicts are kept apart for the sensitivity, never mixed into the policy.
    assert [i.reconciliation_id for i in found.conflicts] == ["s2"]
    assert found.conflicts[0].osm_value == "asphalt"
    assert found.conflicts[0].surface_class is SurfaceClass.ROUGH
    assert found.relationships == {
        "agreement": 1,
        "conflict": 1,
        "source_only_kitchener": 1,
        "source_only_osm": 1,
        "unknown": 1,
    }


def test_an_artifact_the_committed_evidence_does_not_describe_is_refused(tmp_path: Path) -> None:
    folder, committed = write_geo06_artifact(tmp_path)
    document = json.loads(committed.read_text("utf-8"))
    document["artifact"]["files"]["assertions"]["sha256"] = "0" * 64
    committed.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ShadowError, match="committed evidence"):
        load_surface_evidence(folder, committed)


def test_a_city_only_count_that_disagrees_with_the_evidence_is_refused(tmp_path: Path) -> None:
    folder, committed = write_geo06_artifact(tmp_path, eligible_count=943)

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
    # Regression: the blocked path used to cost inf, which no JSON evidence can hold.
    assert custom.cause is not None
    assert custom.cause["route_a_baseline"]["unusable_in_shadow"]
    assert custom.cause["route_a_baseline"]["cost_shadow"] is None
    json.dumps(custom.cause, allow_nan=False)
    # No preset excludes a rough surface: for them it is a cost, and the route moves by weight.
    assert wheelchair.category is Category.ROUTE_CHANGED
    assert wheelchair.blocked == ()


def test_a_hard_change_names_its_rule_segment_and_city_record() -> None:
    net = _fork()
    graph = net.graph()
    gravel = [city(1, 0.0, 100.0, "GRAVEL", "gravel", record=77)]
    plan = plan_overlay(gravel, net.segments, features_of(graph))
    shadow = shadow_graph(graph, plan)
    profile = next(p for p in study_profiles() if p.key == CUSTOM_ROUGH_KEY)
    result, _pair = run_pair(
        _journey(net),
        profile,
        graph,
        shadow,
        plan.fills,
        (surface_lookup(graph), surface_lookup(shadow)),
    )

    [entry] = changed_routes([result], plan, gravel)

    hard = entry["hard_constraint"]
    assert hard["profile_rule"].startswith("exclude_rough_surface")
    assert [b["segment"] for b in hard["blocked_segments"]] == ["a->b#0"]
    assert hard["blocked_segments"][0]["records"] == [77]
    assert hard["consequence"].startswith("the route moves by +")
    assert entry["city_assertions"][0]["raw_value"] == "GRAVEL"
    assert entry["evidence_dating"] == ["capture_dated_only"]


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


# ---------------------------------------------------------------------------
# The whole study, end to end
# ---------------------------------------------------------------------------


def osm_grid(
    conflict_surface: str = "asphalt",
) -> tuple[RoutableGraph, list[SegmentSource], StudyExtract, tuple[float, float, float, float]]:
    """A 4 x 3 grid of 400 m blocks with OSM-style ids, cut at every node, and its extract.

    Way 100 runs along the bottom row with no surface; way 106, the right-hand
    column, is asphalt in OSM.
    """
    nodes: dict[int, tuple[float, float]] = {}
    for row in range(3):
        for col in range(4):
            nodes[row * 4 + col + 1] = at(400.0 * col, 400.0 * row)
    ways: list[tuple[int, list[int], dict[str, str]]] = [
        (100 + row, [row * 4 + col + 1 for col in range(4)], dict(FOOTWAY)) for row in range(3)
    ]
    for col in range(4):
        tags = {"highway": "footway", "surface": conflict_surface} if col == 3 else dict(FOOTWAY)
        ways.append((103 + col, [col + 1 + 4 * row for row in range(3)], tags))
    edges = [
        NetworkEdge(
            source_u=str(u),
            source_v=str(v),
            edge_key=key,
            geometry=LineString([nodes[u], nodes[v]]),
            features=normalise_edge(tags),
            source_way_id=str(way_id),
        )
        for way_id, refs, tags in ways
        for key, (u, v) in enumerate(pairwise(refs))
    ]
    payload = NetworkPayload(
        nodes=[NetworkNode(str(i), Point(*xy)) for i, xy in sorted(nodes.items())], edges=edges
    )
    extract = StudyExtract(
        nodes={i: OsmNode(i, xy[0], xy[1], 1, None, {}) for i, xy in nodes.items()},
        ways={w: OsmWay(w, 1, None, tags, tuple(refs)) for w, refs, tags in ways},
    )
    sources = [SegmentSource(e.source_u, e.source_v, e.edge_key, e.source_way_id) for e in edges]
    lons = [xy[0] for xy in nodes.values()]
    lats = [xy[1] for xy in nodes.values()]
    bounds = (min(lons) - 0.001, min(lats) - 0.001, max(lons) + 0.001, max(lats) + 0.001)
    return graph_from_payload(payload), sources, extract, bounds


def test_the_whole_study_runs_and_leaves_the_baseline_graph_as_it_was(tmp_path: Path) -> None:
    graph, sources, extract, bounds = osm_grid()
    folder, committed = write_geo06_artifact(tmp_path, eligible_way=100, conflict_way=106)
    evidence = load_surface_evidence(folder, committed)

    output = run_study(
        graph,
        sources,
        evidence,
        extract,
        bounds=bounds,
        broad_size=4,
        seed="test",
        per_stratum=2,
        recheck=2,
    )

    # The City's asphalt describes the three segments of way 100, and nothing else.
    assert sorted(f.way_id for f in output.plan.fills.values()) == [100, 100, 100]
    # The conflict sensitivity would put the City's gravel where OSM says asphalt.
    assert {f.replaces for f in output.conflict_plan.fills.values()} == {SurfaceClass.PAVED}
    assert output.isolation["baseline_graph_unchanged"]
    rerouted = output.isolation["baseline_rerouted_after_study"]
    assert rerouted["identical"] == rerouted["routes"] > 0
    assert output.corpora["targeted"]
    assert len(output.results) == 7 * (
        len(output.corpora["broad"]) + len(output.corpora["targeted"])
    )
    assert all(a["agree"] for a in output.agreement)

    queue = validation_queue(evidence, output, graph)
    dataset = ActiveDataset(uuid.uuid4(), "i" * 64, "fixture", "c" * 64, 2)
    document = shadow_evidence(
        evidence=evidence,
        output=output,
        dataset_before=dataset,
        dataset_after=dataset,
        extract_sha256="x" * 64,
        seed="test",
        queue=queue,
        attribution={"openstreetmap": "© OpenStreetMap contributors"},
    )
    page = render_changes(
        output.results,
        output.pairs,
        {p.key: p for p in study_profiles()},
        output.plan.fills,
        {"openstreetmap": "© OpenStreetMap contributors"},
    )

    assert json.loads(json.dumps(document))["production_isolation"]["database"]["unchanged"]
    assert document["surface_evidence"]["city_only"]["outcome"] == {"filled": 1}
    assert document["label"] == WATERMARK
    assert WATERMARK in page
    for entry in queue:
        assert entry["provenance"]["routing_eligibility"] == "not_routing_eligible"


@pytest.mark.parametrize(
    ("osm_surface", "city"),
    [("asphalt", ("GRAVEL", "gravel")), ("gravel", ("ASPHALT", "asphalt"))],
)
def test_the_pruned_conflict_sensitivity_is_the_exhaustive_one(
    tmp_path: Path, osm_surface: str, city: tuple[str, str]
) -> None:
    # Pruning skips only journeys the City's side provably cannot move; in both
    # directions — a conflict segment made dearer, and one made cheaper — it
    # must give exactly what routing every journey again gives.
    graph, sources, extract, bounds = osm_grid(conflict_surface=osm_surface)
    folder, committed = write_geo06_artifact(
        tmp_path, eligible_way=100, conflict_way=106, conflict_city=city, conflict_osm=osm_surface
    )
    evidence = load_surface_evidence(folder, committed)

    def study(prune: bool) -> Any:
        return run_study(
            graph,
            sources,
            evidence,
            extract,
            bounds=bounds,
            broad_size=6,
            seed="test",
            per_stratum=2,
            recheck=1,
            prune=prune,
        )

    pruned, full = study(True), study(False)

    def outcome(result: Any) -> tuple[Any, ...]:
        return (
            result.journey.journey_id,
            result.profile_key,
            str(result.category),
            json.dumps(result.shadow.outcome(), sort_keys=True, default=str),
        )

    assert sorted(map(outcome, pruned.sensitivity)) == sorted(map(outcome, full.sensitivity))
    assert pruned.sensitivity_rerouted <= full.sensitivity_rerouted == len(full.sensitivity)


def test_a_cheaper_segment_far_from_both_ends_matters_only_within_the_bound() -> None:
    # A 20 m conflict segment 1 km from each end of a 2 km journey: any route
    # through it costs at least 2 km, less the snap allowance at each end.
    positions = {"u": at(1000, 300), "v": at(1020, 300)}
    lengths = {"u->v#0": 20.0}
    journey = Journey("P000", "test", at(0, 0), at(2000, 0))
    cheaper = OverlayPlan(
        CONFLICT_SENSITIVITY,
        fills={
            "u->v#0": Fill(
                "u->v#0",
                1,
                0.0,
                20.0,
                "asphalt",
                SurfaceClass.PAVED,
                1.0,
                (1,),
                ("r",),
                replaces=SurfaceClass.ROUGH,
            )
        },
    )
    dearer = OverlayPlan(
        CONFLICT_SENSITIVITY,
        fills={
            "u->v#0": Fill(
                "u->v#0",
                1,
                0.0,
                20.0,
                "gravel",
                SurfaceClass.ROUGH,
                1.0,
                (1,),
                ("r",),
                replaces=SurfaceClass.PAVED,
            )
        },
    )
    wheelchair = get_profile("wheelchair")

    def base(cost: float) -> RouteFacts:
        return RouteFacts(True, path=("x",), effective_m=cost)

    assert may_move(journey, wheelchair, base(2500.0), cheaper, positions, lengths)
    assert not may_move(journey, wheelchair, base(1500.0), cheaper, positions, lengths)
    # Dearer and on no route: it cannot matter, however expensive the journey.
    assert not may_move(journey, wheelchair, base(9000.0), dearer, positions, lengths)
    # Any change on a route already travelled is routed again.
    touching = RouteFacts(True, path=("u->v#0",), effective_m=1500.0, overlay_m=20.0)
    assert may_move(journey, wheelchair, touching, dearer, positions, lengths)


def test_only_the_blocking_record_is_queued_for_a_feasibility_change(tmp_path: Path) -> None:
    # Regression: the queue credited every City record on either path with the
    # feasibility change, including asphalt the new route merely runs along.
    net = _fork()
    graph = net.graph()
    items = [
        city(1, 0.0, 100.0, "GRAVEL", "gravel", record=77),
        city(2, 0.0, 115.0, record=88),
    ]
    plan = plan_overlay(items, net.segments, features_of(graph))
    shadow = shadow_graph(graph, plan)
    lookups = (surface_lookup(graph), surface_lookup(shadow))
    profile = next(p for p in study_profiles() if p.key == CUSTOM_ROUGH_KEY)
    result, _pair = run_pair(_journey(net), profile, graph, shadow, plan.fills, lookups)
    assert result.category is Category.FEASIBILITY_CHANGED
    evidence = SurfaceEvidence(items, [], {}, {})
    output = StudyOutput(
        plan=plan,
        conflict_plan=OverlayPlan(CONFLICT_SENSITIVITY),
        locate_problems=Counter(),
        corpora={"broad": [], "targeted": []},
        results=[result],
        sensitivity=[],
        pairs={},
        agreement=[],
        isolation={},
        network={},
        timings={},
        memory={},
    )

    queue = validation_queue(evidence, output, graph)

    feasibility = [e["record_id"] for e in queue if "feasibility_change" in e["selected_for"]]
    assert feasibility == [77]
