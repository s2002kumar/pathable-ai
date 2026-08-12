"""Checksums, validation and the synthetic fixture.

These three are tested together because they answer one question: can we tell
whether two ingestions produced the same network, and whether that network is
fit to route on?
"""

from __future__ import annotations

import dataclasses

from shapely.geometry import LineString, Point

from pathable_api.geo.checksum import dataset_checksum
from pathable_api.geo.enums import AccessValue, KerbType, Severity, SurfaceClass, TriState
from pathable_api.geo.features import EdgeFeatures, normalise_edge
from pathable_api.geo.fixtures import EDGES, NODES, build_synthetic_network
from pathable_api.geo.network import NetworkEdge, NetworkNode, NetworkPayload
from pathable_api.geo.validation import validate_network


def _node(name: str, lon: float, lat: float) -> NetworkNode:
    return NetworkNode(source_node_id=name, geometry=Point(lon, lat))


def _edge(u: str, v: str, coords: list[tuple[float, float]], **kwargs: object) -> NetworkEdge:
    features = kwargs.pop("features", normalise_edge({"highway": "footway"}))
    assert isinstance(features, EdgeFeatures)
    return NetworkEdge(
        source_u=u,
        source_v=v,
        edge_key=0,
        geometry=LineString(coords),
        features=features,
        **kwargs,  # type: ignore[arg-type]
    )


def _tiny_network() -> NetworkPayload:
    return NetworkPayload(
        nodes=[_node("a", -80.54, 43.47), _node("b", -80.538, 43.47)],
        edges=[_edge("a", "b", [(-80.54, 43.47), (-80.538, 43.47)])],
    )


class TestChecksum:
    def test_identical_content_hashes_identically(self) -> None:
        assert _tiny_network().checksum() == _tiny_network().checksum()

    def test_insertion_order_does_not_change_the_checksum(self) -> None:
        # OSMnx does not guarantee iteration order between runs, so a checksum
        # sensitive to it would report a change on every re-import.
        payload = _tiny_network()
        reversed_payload = NetworkPayload(
            nodes=list(reversed(payload.nodes)), edges=list(payload.edges)
        )
        assert payload.checksum() == reversed_payload.checksum()

    def test_moving_a_node_changes_the_checksum(self) -> None:
        moved = NetworkPayload(
            nodes=[_node("a", -80.54, 43.47), _node("b", -80.537, 43.47)],
            edges=_tiny_network().edges,
        )
        assert moved.checksum() != _tiny_network().checksum()

    def test_changing_a_routing_attribute_changes_the_checksum(self) -> None:
        original = _tiny_network()
        changed = NetworkPayload(
            nodes=original.nodes,
            edges=[
                _edge(
                    "a",
                    "b",
                    [(-80.54, 43.47), (-80.538, 43.47)],
                    features=normalise_edge({"highway": "steps", "step_count": "8"}),
                )
            ],
        )
        assert changed.checksum() != original.checksum()

    def test_sub_centimetre_coordinate_noise_is_ignored(self) -> None:
        # Re-projection jitter in the ninth decimal place is ~0.1 mm. Treating
        # that as a new dataset would make versioning meaningless.
        stable = dataset_checksum([("a", -80.5400000001, 43.4700000002)], [])
        assert stable == dataset_checksum([("a", -80.54, 43.47)], [])

    def test_attribute_order_within_an_edge_is_irrelevant(self) -> None:
        forward = dataset_checksum([], [("a", "b", 0, 10.0, False, [("x", 1), ("y", 2)])])
        backward = dataset_checksum([], [("a", "b", 0, 10.0, False, [("y", 2), ("x", 1)])])
        assert forward == backward

    def test_a_null_attribute_is_distinct_from_the_string_none(self) -> None:
        null = dataset_checksum([], [("a", "b", 0, 10.0, False, [("surface", None)])])
        text = dataset_checksum([], [("a", "b", 0, 10.0, False, [("surface", "none")])])
        assert null != text


class TestValidation:
    def test_a_well_formed_network_passes(self) -> None:
        report = validate_network(_tiny_network())
        assert report.is_valid
        assert report.errors == ()

    def test_an_empty_network_is_rejected(self) -> None:
        report = validate_network(NetworkPayload(nodes=[], edges=[]))
        codes = {finding.code for finding in report.errors}
        assert codes == {"dataset.no_nodes", "dataset.no_edges"}
        assert not report.is_valid

    def test_an_edge_referencing_a_missing_node_is_an_error(self) -> None:
        payload = _tiny_network()
        payload.edges.append(_edge("a", "ghost", [(-80.54, 43.47), (-80.539, 43.471)]))

        report = validate_network(payload)
        assert not report.is_valid
        finding = next(f for f in report.errors if f.code == "edge.missing_endpoint_node")
        assert finding.details["missing_node"] == "ghost"

    def test_duplicate_node_identities_are_an_error(self) -> None:
        payload = _tiny_network()
        payload.nodes.append(_node("a", -80.53, 43.47))

        report = validate_network(payload)
        assert any(f.code == "node.duplicate_identity" for f in report.errors)

    def test_duplicate_edge_identities_are_an_error(self) -> None:
        payload = _tiny_network()
        payload.edges.append(_edge("a", "b", [(-80.54, 43.47), (-80.538, 43.47)]))

        report = validate_network(payload)
        assert any(f.code == "edge.duplicate_identity" for f in report.errors)

    def test_a_zero_length_edge_is_an_error(self) -> None:
        payload = _tiny_network()
        payload.edges[0] = _edge("a", "b", [(-80.54, 43.47), (-80.54, 43.47)])

        report = validate_network(payload)
        assert any(f.code == "edge.non_positive_length" for f in report.errors)

    def test_invalid_coordinates_are_an_error(self) -> None:
        payload = NetworkPayload(nodes=[_node("a", 999.0, 43.47)], edges=_tiny_network().edges)
        report = validate_network(payload)
        assert any(f.code == "node.invalid_coordinates" for f in report.errors)

    def test_geometry_outside_the_declared_region_is_an_error(self) -> None:
        report = validate_network(_tiny_network(), declared_bounds=(0.0, 0.0, 1.0, 1.0))
        assert any(f.code == "dataset.geometry_outside_bounds" for f in report.errors)

    def test_geometry_inside_the_declared_region_passes(self) -> None:
        report = validate_network(_tiny_network(), declared_bounds=(-80.6, 43.4, -80.4, 43.5))
        assert report.is_valid

    def test_count_disagreement_is_an_error(self) -> None:
        report = validate_network(_tiny_network(), expected_node_count=99)
        assert any(f.code == "dataset.node_count_mismatch" for f in report.errors)

    def test_missing_accessibility_data_warns_but_does_not_block(self) -> None:
        # Real OSM extracts are full of gaps. Blocking on them would mean no real
        # dataset could ever go live, which would push everyone toward disabling
        # validation entirely.
        payload = NetworkPayload(
            nodes=_tiny_network().nodes,
            edges=[_edge("a", "b", [(-80.54, 43.47), (-80.538, 43.47)], features=EdgeFeatures())],
        )
        report = validate_network(payload)

        assert report.is_valid
        warning = next(f for f in report.warnings if f.code == "edge.missing_accessibility_data")
        assert warning.severity is Severity.WARNING
        assert "surface" in warning.details["attributes"]

    def test_the_summary_is_bounded(self) -> None:
        # A dataset with tens of thousands of warnings must not write a
        # tens-of-thousands-element blob into every dataset row.
        nodes = [_node(f"n{i}", -80.54 + i * 1e-4, 43.47) for i in range(300)]
        edges = [
            _edge(
                f"n{i}",
                f"n{i + 1}",
                [(-80.54 + i * 1e-4, 43.47), (-80.54 + (i + 1) * 1e-4, 43.47)],
                features=EdgeFeatures(),
            )
            for i in range(299)
        ]
        report = validate_network(NetworkPayload(nodes=nodes, edges=edges))
        summary = report.summary()

        assert summary["valid"] is True
        assert summary["warning_count"] == 299
        assert len(summary["findings"]) == 200
        assert summary["truncated"] is True


class TestSyntheticFixture:
    def test_it_is_deterministic(self) -> None:
        assert build_synthetic_network().checksum() == build_synthetic_network().checksum()

    def test_it_validates_without_errors(self) -> None:
        payload = build_synthetic_network()
        report = validate_network(
            payload,
            declared_bounds=(-80.5450, 43.4650, -80.5300, 43.4750),
            expected_node_count=payload.node_count,
            expected_edge_count=payload.edge_count,
        )
        assert report.errors == ()

    def test_it_contains_the_comparison_the_product_is_about(self) -> None:
        payload = build_synthetic_network()
        by_identity = {(edge.source_u, edge.source_v): edge for edge in payload.edges}

        stairs = by_identity[("B", "C")]
        assert stairs.features.steps is TriState.YES
        assert stairs.features.step_count == 14

        bypass = [by_identity[("B", "F")], by_identity[("F", "C")]]
        assert all(edge.features.steps is TriState.NO for edge in bypass)
        assert all(edge.features.surface_class is SurfaceClass.PAVED for edge in bypass)

        # The step-free route has to be genuinely longer, or the comparison
        # would have nothing to trade off.
        direct = stairs.length
        detour = sum(edge.length for edge in bypass)
        assert detour > direct

    def test_it_covers_the_cases_the_cost_model_must_handle(self) -> None:
        payload = build_synthetic_network()
        by_identity = {(edge.source_u, edge.source_v): edge for edge in payload.edges}

        # An unknown kerb on a real crossing.
        unmarked = by_identity[("C", "D")]
        assert unmarked.features.is_crossing is True
        assert unmarked.features.kerb is KerbType.UNKNOWN

        # A known-good crossing.
        signalised = by_identity[("C", "E")]
        assert signalised.features.kerb is KerbType.LOWERED

        # Rough and steep.
        assert by_identity[("A", "G")].features.surface_class is SurfaceClass.ROUGH
        steep = by_identity[("G", "B")].features.incline_percent
        assert steep is not None
        assert steep >= 10.0

        # Wholly untagged.
        untagged = by_identity[("A", "U")]
        assert untagged.features.steps is TriState.UNKNOWN
        assert untagged.features.surface_class is SurfaceClass.UNKNOWN

        # A one-way passage and a foot-prohibited shortcut.
        assert by_identity[("H", "A")].directed is True
        assert by_identity[("B", "E")].features.foot_access is AccessValue.NO

    def test_every_node_it_references_exists(self) -> None:
        referenced = {name for u, v, _, _ in EDGES for name in (u, v)}
        assert referenced <= set(NODES)

    def test_bounds_are_reported_over_the_whole_network(self) -> None:
        bounds = build_synthetic_network().bounds()
        assert bounds is not None
        min_lon, _min_lat, _max_lon, max_lat = bounds
        assert min_lon == min(lon for lon, _ in NODES.values())
        assert max_lat == max(lat for _, lat in NODES.values())


class TestEdgeLength:
    def test_length_is_geodesic_not_degrees(self) -> None:
        # 0.002 degrees of longitude at 43.47°N is about 162 m, not 0.002.
        edge = _edge("a", "b", [(-80.540, 43.470), (-80.538, 43.470)])
        assert 155.0 < edge.length < 170.0

    def test_a_supplied_length_wins_over_the_computed_one(self) -> None:
        # OSMnx already projects and measures; recomputing would disagree
        # slightly and make checksums differ between equivalent imports.
        edge = dataclasses.replace(
            _edge("a", "b", [(-80.540, 43.470), (-80.538, 43.470)]), length_m=42.0
        )
        assert edge.length == 42.0
