"""Reconciling what OSM and the City each assert, on invented streets.

What the tests protect:

- only the correspondences PA-GEO-05 earned reach reconciliation, and every
  other decision is excluded with its reason;
- a curb cut stays at its kerb node and never spreads along a way;
- raw values, value states and typed dates survive; a template default is
  kept but never read as evidence;
- a conflict keeps both assertions and resolves nothing;
- agreement and independence stay separate fields;
- nothing can reach routing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, box

from pathable_api.geo.kitchener.assertions import (
    NOT_ROUTING_ELIGIBLE,
    Blocker,
    LineageRelationship,
    Reconciliation,
    Relationship,
    Source,
    Topic,
)
from pathable_api.geo.kitchener.conflation import (
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    ConflationInputs,
    Decision,
    Population,
    Record,
    RelationshipIndex,
    Target,
)
from pathable_api.geo.kitchener.correspondence import KitchenerFeature, KitchenerIndex
from pathable_api.geo.kitchener.lineage import ElementHistory
from pathable_api.geo.kitchener.osm_history import Changeset, Contribution
from pathable_api.geo.kitchener.reconciliation import (
    SURVEY_APP_EDIT,
    CityFields,
    Exclusion,
    KerbLocation,
    Reconciled,
    attach_history,
    invariant_violations,
    reconcile,
)
from pathable_api.geo.kitchener.reconciliation_run import (
    Geo05Artifact,
    RunInputs,
    reconciliation_evidence,
    run_reconciliation,
    target_geometry,
    write_reconciliation_artifact,
)
from pathable_api.geo.kitchener.study import History
from tests.unit.kitchener_streets import SIDEWALK, Street

KERB_LOWERED = {"barrier": "kerb", "kerb": "lowered"}


def _record(
    record_id: int,
    points: list[tuple[float, float]],
    *,
    curb_cut: bool = False,
    surface: str = "CONCRETE",
    surface_state: str = "template_default",
    structure: str | None = None,
    railing: str = "N",
    railing_state: str = "template_default",
) -> Record:
    geometry = LineString(points)
    return Record(
        activetransportid=record_id,
        network_role="pedestrian_way",
        family="sidewalk",
        subcategory="SIDEWALK",
        structure=structure,
        curb_cut=curb_cut,
        surface_material=surface if surface_state == "non_default" else None,
        length_m=float(geometry.length),
        street=None,
        geometry=geometry,
        attributes={
            "feature_type": structure or "SURFACE",
            "origin_feature_type": "administrative_assertion" if structure else "template_default",
            "curbcut": "Y" if curb_cut else "N",
            "state_curbcut": "non_default" if curb_cut else "template_default",
            "origin_curbcut": "administrative_assertion" if curb_cut else "template_default",
            "surface_material": surface,
            "state_surface_material": surface_state,
            "origin_surface_material": (
                "administrative_assertion" if surface_state == "non_default" else surface_state
            ),
            "railing": railing,
            "state_railing": railing_state,
            "origin_railing": "administrative_assertion",
            "source_class": "orthoimagery",
            # PA-GEO-05's records format SOURCE_DATE themselves; the
            # reconciliation reads its own, in UTC, and must not use this one.
            "source_date": "2016-04-30",
            "last_inspection_year": "2026",
            "publications": ["Active_Transportation"],
        },
    )


def _fields(record: Record) -> CityFields:
    return CityFields(
        created_at="2014-06-30T00:00:00Z",
        modified_at="2026-08-24T00:00:00Z",
        state_feature_type="non_default" if record.structure else "template_default",
        source_date="2016-05-01",
    )


def _way(way: str, from_m: float, to_m: float) -> Target:
    return Target(way, "carrier", from_m, to_m)


def _matched(
    record_id: int,
    targets: tuple[Target, ...],
    rule: str = "covered_by_carriers",
    relationship: str = "one_to_one",
    **signals: Any,
) -> Decision:
    return Decision(record_id, MATCHED, rule, targets, relationship, "separate_way", signals)


class Scene:
    """An invented street, its City records, and PA-GEO-05-style decisions."""

    def __init__(self) -> None:
        self.street = Street()
        self.records: dict[int, Record] = {}
        self.decisions: dict[int, Decision] = {}

    def add(self, record: Record, decision: Decision) -> None:
        self.records[record.activetransportid] = record
        self.decisions[record.activetransportid] = decision

    def run(self, *, history: History | None = None) -> Reconciled:
        index = self.street.index()
        physical = KitchenerIndex.build(
            KitchenerFeature(
                r.activetransportid, "physical_active", r.network_role, "X", r.geometry
            )
            for r in self.records.values()
        )
        cuts = KitchenerIndex.build(
            f for i, f in physical.features.items() if self.records[i].curb_cut
        )
        city_fields = {i: _fields(r) for i, r in self.records.items()}
        found = reconcile(
            self.records,
            self.decisions,
            index,
            area=box(-10_000, -10_000, 10_000, 10_000),
            city_physical=physical,
            city_curb_cuts=cuts,
            city_fields=city_fields,
        )
        if history is not None:
            attach_history(found, self.records, history, city_fields, index)
        assert invariant_violations(found, index) == []
        return found


def _rows(found: Reconciled, topic: Topic) -> list[Reconciliation]:
    return [r for r in found.reconciliations if r.topic is topic]


# ---------------------------------------------------------------------------
# The accepted input contract
# ---------------------------------------------------------------------------


def test_ambiguous_and_unmatched_decisions_reconcile_nothing_and_say_why() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        Decision(1, AMBIGUOUS, "competing_way", (), None, "none", {}),
    )
    scene.add(
        _record(2, [(10, 50), (90, 50)], surface="ASPHALT", surface_state="non_default"),
        Decision(2, UNMATCHED, "no_counterpart", (), None, "none", {}),
    )

    found = scene.run()

    assert [r for r in found.reconciliations if r.source_records] == []
    assert found.gates[1].exclusions[Topic.SURFACE] is Exclusion.AMBIGUOUS
    assert found.gates[2].exclusions[Topic.SURFACE] is Exclusion.NO_COUNTERPART


def test_a_curb_cut_reconciles_only_at_its_kerb_node_never_along_the_way() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (400, 1)], {**SIDEWALK, "surface": "concrete"})
    kerb = scene.street.node(200, 1, KERB_LOWERED)
    record = _record(
        1, [(199, 0), (201, 0)], curb_cut=True, surface="ASPHALT", surface_state="non_default"
    )
    scene.add(
        record,
        _matched(
            1,
            (Target(f"node/{kerb}", "kerb"), _way("way/1", 199.0, 201.0)),
            rule="curb_cut_kerb_and_carrier",
        ),
    )

    found = scene.run()

    [row] = found.reconciliations
    assert row.topic is Topic.CURB_RAMP
    assert row.target.element == f"node/{kerb}"
    # The way-level set of a curb-cut decision is PA-GEO-05's weak class: no
    # surface is reconciled on it, though both sides have one.
    assert found.gates[1].exclusions[Topic.SURFACE] is Exclusion.CURB_CUT_WAY_LEVEL
    assert row.relationship is Relationship.COMPATIBLE


def test_curb_cut_y_is_kept_as_a_ramp_never_as_a_kerb_height() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], SIDEWALK)
    kerb = scene.street.node(50, 1, KERB_LOWERED)
    scene.add(
        _record(1, [(49, 0), (51, 0)], curb_cut=True),
        _matched(1, (Target(f"node/{kerb}", "kerb"),), rule="curb_cut_kerb_node"),
    )

    found = scene.run()

    [row] = found.reconciliations
    [city] = [found.assertions[a] for a in row.kitchener_assertions]
    [osm] = [found.assertions[a] for a in row.osm_assertions]
    assert (city.raw_attribute, city.raw_value, city.normalized_value) == (
        "CURBCUT",
        "Y",
        "curb_ramp_present",
    )
    assert (osm.raw_attribute, osm.raw_value, osm.normalized_value) == (
        "kerb",
        "lowered",
        "lowered",
    )
    assert city.prop != osm.prop


def test_a_curb_cut_matched_only_way_level_is_excluded() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], SIDEWALK)
    scene.add(
        _record(1, [(49, 0), (51, 0)], curb_cut=True),
        _matched(1, (_way("way/1", 49.0, 51.0),), rule="curb_cut_carrier"),
    )

    found = scene.run()

    assert found.reconciliations == []
    assert found.gates[1].exclusions[Topic.CURB_RAMP] is Exclusion.CURB_CUT_WITHOUT_KERB_NODE


def test_two_curb_cuts_on_one_kerb_node_make_one_many_to_one_row() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], SIDEWALK)
    kerb = scene.street.node(50, 1, KERB_LOWERED)
    for record_id, x in ((1, 48.0), (2, 52.0)):
        scene.add(
            _record(record_id, [(x - 1, 0), (x + 1, 0)], curb_cut=True),
            _matched(record_id, (Target(f"node/{kerb}", "kerb"),), rule="curb_cut_kerb_node"),
        )

    found = scene.run()

    [row] = _rows(found, Topic.CURB_RAMP)
    assert row.source_records == (1, 2)
    assert row.correspondence_relationship == "many_to_one"
    assert len(row.kitchener_assertions) == 2
    assert len(row.osm_assertions) == 1


def test_a_surface_attaches_to_the_metres_the_record_covers_not_the_whole_way() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(
        _record(1, [(40, 0), (60, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 40.0, 60.0),)),
    )

    found = scene.run()

    [row] = _rows(found, Topic.SURFACE)
    assert (row.target.from_m, row.target.to_m) == (40.0, 60.0)
    assert target_geometry(row, scene.street.index()).length == pytest.approx(20.0)
    assert row.relationship is Relationship.AGREEMENT


def test_short_pieces_are_excluded_from_way_level_reconciliation() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(
        _record(1, [(50, 0), (54, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 50.0, 54.0),)),
    )

    found = scene.run()

    assert found.reconciliations == []
    assert found.gates[1].exclusions[Topic.SURFACE] is Exclusion.SHORT_PIECE


def test_a_city_stair_osm_draws_as_a_plain_footway_waits_for_matcher_v2() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (30, 1)], {"highway": "footway", "surface": "concrete"})
    scene.add(
        _record(1, [(5, 0), (25, 0)], structure="STAIRS"),
        _matched(1, (_way("way/1", 5.0, 25.0),)),
    )

    found = scene.run()

    assert found.reconciliations == []
    assert found.gates[1].exclusions[Topic.STRUCTURE] is Exclusion.STRUCTURE_NOT_IN_OSM
    assert found.gates[1].exclusions[Topic.SURFACE] is Exclusion.STRUCTURE_NOT_IN_OSM


def test_a_city_stair_on_osm_steps_is_agreement_with_both_assertions() -> None:
    # Regression: PA-GEO-05's records carry no FEATURE_TYPE value state, so the
    # first full-pilot run withheld every City structure assertion while still
    # calling the rows agreement. The state now comes from the normalized file.
    scene = Scene()
    scene.street.line(1, [(0, 1), (30, 1)], {"highway": "steps", "handrail": "yes"})
    scene.add(
        _record(1, [(5, 0), (25, 0)], structure="STAIRS", railing="Y", railing_state="non_default"),
        _matched(1, (_way("way/1", 5.0, 25.0),), structure_carriers=["way/1"]),
    )

    found = scene.run()

    [steps] = [r for r in _rows(found, Topic.STRUCTURE) if r.prop == "structure:steps"]
    assert steps.relationship is Relationship.AGREEMENT
    assert steps.kitchener_values == ("STAIRS",)
    assert steps.osm_values == ("steps",)
    [railing] = _rows(found, Topic.RAILING)
    assert railing.relationship is Relationship.COMPATIBLE
    assert not railing.routing_property
    assert str(Blocker.NOT_A_ROUTING_PROPERTY) in railing.blockers


def test_a_structure_only_osm_records_is_osm_only_with_the_city_default_withheld() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (30, 1)], {"highway": "steps"})
    scene.add(_record(1, [(5, 0), (25, 0)]), _matched(1, (_way("way/1", 5.0, 25.0),)))

    found = scene.run()

    [row] = _rows(found, Topic.STRUCTURE)
    assert row.relationship is Relationship.SOURCE_ONLY_OSM
    assert row.kitchener_assertions == ()
    [withheld] = [found.assertions[a] for a in row.kitchener_withheld]
    assert (withheld.raw_value, withheld.value_state, withheld.usable) == (
        "SURFACE",
        "template_default",
        False,
    )


# ---------------------------------------------------------------------------
# Values, defaults, conflicts, dates
# ---------------------------------------------------------------------------


def test_a_template_default_is_kept_but_never_evidence() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(_record(1, [(10, 0), (90, 0)]), _matched(1, (_way("way/1", 10.0, 90.0),)))

    found = scene.run()

    [row] = _rows(found, Topic.SURFACE)
    # CONCRETE is the City's template default: OSM alone asserts a surface here.
    assert row.relationship is Relationship.SOURCE_ONLY_OSM
    assert [found.assertions[a].raw_value for a in row.kitchener_withheld] == ["CONCRETE"]
    assert str(Blocker.LICENSING) not in row.blockers


def test_a_conflict_keeps_both_raw_values_and_resolves_nothing() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "concrete"})
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="BRICK", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )

    found = scene.run()

    [row] = _rows(found, Topic.SURFACE)
    assert row.relationship is Relationship.CONFLICT
    assert (row.kitchener_values, row.osm_values) == (("BRICK",), ("concrete",))
    assert row.conflict is not None
    assert row.conflict.startswith("unresolved")
    names = {f.name for f in fields(Reconciliation)}
    assert not names & {"value", "resolved_value", "chosen_value", "confidence", "winner"}


def test_raw_and_normalized_values_are_kept_apart() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT (PAINTED)", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )

    found = scene.run()

    city = found.assertions["kitchener/1#surface_material"]
    assert (city.raw_value, city.normalized_value, city.value_state) == (
        "ASPHALT (PAINTED)",
        "asphalt",
        "non_default",
    )
    assert city.evidence_origin == "administrative_assertion"


def test_every_date_keeps_what_it_dates_and_only_an_observation_is_freshness() -> None:
    scene = Scene()
    scene.street.line(
        1,
        [(0, 1), (100, 1)],
        {**SIDEWALK, "surface": "asphalt", "check_date:surface": "2025-06-01"},
    )
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )

    found = scene.run()

    city = found.assertions["kitchener/1#surface_material"].dates
    assert city.source_capture_date == "2016-05-01"
    # Regression: the normalized file holds the year as text; it is kept as a year.
    assert city.inspection_year == 2026
    assert city.record_created_at == "2014-06-30T00:00:00Z"
    # UPDATE_DATE is a bulk maintenance day: kept, never freshness.
    assert city.record_modified_at == "2026-08-24T00:00:00Z"
    assert city.observation_date is None
    assert city.freshness_basis == "no_observation_date"
    [osm_id] = _rows(found, Topic.SURFACE)[0].osm_assertions
    osm = found.assertions[osm_id].dates
    assert (osm.observation_date, osm.observation_date_basis) == (
        "2025-06-01",
        "check_date:surface",
    )
    assert osm.osm_edit_timestamp == "2024-01-01T00:00:00Z"
    assert osm.freshness_basis == "observation_date"


# ---------------------------------------------------------------------------
# OSM's kerbs where the City records no curb cut
# ---------------------------------------------------------------------------


def test_osm_kerbs_without_a_city_curb_cut_are_found_by_location_only() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], SIDEWALK)
    covered = scene.street.node(20, 1, KERB_LOWERED)  # a City sidewalk here, no curb cut
    near_cut = scene.street.node(80, 1, KERB_LOWERED)  # a City curb cut 2 m away, unaccepted
    far = scene.street.node(5000, 5000, KERB_LOWERED)  # nothing of the City's near
    scene.add(_record(1, [(0, 0), (60, 0)]), _matched(1, (_way("way/1", 0.0, 60.0),)))
    scene.add(
        _record(2, [(81, 0), (83, 0)], curb_cut=True),
        Decision(2, AMBIGUOUS, "curb_cut_two_kerb_nodes", (), None, "none", {}),
    )

    found = scene.run()

    assert found.kerb_locations == {
        covered: KerbLocation.CITY_COVERED,
        near_cut: KerbLocation.CITY_CURB_CUT_NEAR,
        far: KerbLocation.OUTSIDE_CITY_COVERAGE,
    }
    [row] = _rows(found, Topic.CURB_RAMP)
    assert row.target.element == f"node/{covered}"
    assert row.relationship is Relationship.SOURCE_ONLY_OSM
    # No correspondence to a City record is claimed for it.
    assert row.source_records == ()


# ---------------------------------------------------------------------------
# Routing isolation and the invariants
# ---------------------------------------------------------------------------


def test_every_reconciliation_is_blocked_from_routing_and_says_why() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "concrete"})
    kerb = scene.street.node(100, 1, KERB_LOWERED)
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    scene.add(
        _record(2, [(99, 0), (101, 0)], curb_cut=True),
        _matched(2, (Target(f"node/{kerb}", "kerb"),), rule="curb_cut_kerb_node"),
    )

    found = scene.run()

    assert found.reconciliations
    for row in found.reconciliations:
        assert row.routing_eligibility == NOT_ROUTING_ELIGIBLE
        assert str(Blocker.ROUTING_POLICY) in row.blockers
        if row.kitchener_assertions:
            assert {str(Blocker.LICENSING), str(Blocker.VALIDATION)} <= set(row.blockers)


def test_the_invariants_refuse_agreement_without_a_city_assertion() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (30, 1)], {"highway": "steps"})
    scene.add(
        _record(1, [(5, 0), (25, 0)], structure="STAIRS"),
        _matched(1, (_way("way/1", 5.0, 25.0),), structure_carriers=["way/1"]),
    )
    found = scene.run()
    [row] = _rows(found, Topic.STRUCTURE)
    # The first full-pilot run's bug, rebuilt: the City assertion withheld, the row still "agreement".
    broken = replace(row, kitchener_assertions=(), kitchener_withheld=row.kitchener_assertions)
    found.reconciliations = [broken]

    problems = invariant_violations(found, scene.street.index())

    assert any("without an assertion from each source" in p for p in problems)


def test_the_invariants_refuse_a_curb_ramp_on_a_way() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    found = scene.run()
    [row] = found.reconciliations
    found.reconciliations = [replace(row, topic=Topic.CURB_RAMP)]

    assert any(
        "beyond its kerb node" in p for p in invariant_violations(found, scene.street.index())
    )


# ---------------------------------------------------------------------------
# Lineage: agreement is not independence
# ---------------------------------------------------------------------------


def _history(
    element: str, contributions: list[Contribution], changesets: list[Changeset]
) -> History:
    return History(
        {element: ElementHistory(element, tuple(contributions), True)},
        {c.id: c for c in changesets},
        {},
    )


def _contribution(
    element: str, when: str, changeset: int, tags: Mapping[str, str], *, creation: bool
) -> Contribution:
    return Contribution(
        element, when, 1, changeset, creation, False, creation, not creation, dict(tags)
    )


def _surface_agreement(changeset_tags: dict[str, str]) -> Reconciliation:
    scene = Scene()
    tags = {**SIDEWALK, "surface": "asphalt"}
    scene.street.line(1, [(0, 1), (100, 1)], tags)
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    history = _history(
        "way/1",
        [
            _contribution("way/1", "2012-01-01T00:00:00Z", 1, SIDEWALK, creation=True),
            _contribution("way/1", "2020-05-01T00:00:00Z", 2, tags, creation=False),
        ],
        [
            Changeset(1, "2012-01-01T00:00:00Z", None, 1, None, {"source": "survey"}),
            Changeset(2, "2020-05-01T00:00:00Z", None, 1, None, changeset_tags),
        ],
    )
    [row] = _rows(scene.run(history=history), Topic.SURFACE)
    return row


def test_agreement_through_shared_photographs_stays_agreement_and_is_not_independent() -> None:
    row = _surface_agreement({"created_by": "iD 2.30", "imagery_used": "Esri World Imagery"})

    assert row.relationship is Relationship.AGREEMENT
    assert row.lineage is LineageRelationship.POSSIBLE_SHARED


def test_agreement_from_a_survey_app_is_apparently_independent_and_still_just_agreement() -> None:
    row = _surface_agreement({"created_by": "StreetComplete 58.0"})

    assert row.relationship is Relationship.AGREEMENT
    assert row.lineage is LineageRelationship.APPARENTLY_INDEPENDENT
    assert row.lineage_basis == "declared"


def test_a_survey_a_mapper_typed_is_independent_but_dates_no_observation() -> None:
    scene = Scene()
    tags = {**SIDEWALK, "surface": "asphalt"}
    scene.street.line(1, [(0, 1), (100, 1)], tags)
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    history = _history(
        "way/1",
        [_contribution("way/1", "2020-05-01T00:00:00Z", 2, tags, creation=True)],
        [Changeset(2, "2020-05-01T00:00:00Z", None, 1, None, {"source": "survey"})],
    )

    found = scene.run(history=history)

    [row] = _rows(found, Topic.SURFACE)
    assert row.lineage is LineageRelationship.APPARENTLY_INDEPENDENT
    [osm_id] = row.osm_assertions
    # "source=survey" does not say when the survey was.
    assert found.assertions[osm_id].dates.observation_date is None


def test_a_kerb_value_keeps_its_own_lineage_apart_from_the_node_geometry() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], SIDEWALK)
    kerb = scene.street.node(50, 1, KERB_LOWERED)
    element = f"node/{kerb}"
    scene.add(
        _record(1, [(49, 0), (51, 0)], curb_cut=True),
        _matched(1, (Target(element, "kerb"),), rule="curb_cut_kerb_node"),
    )
    history = _history(
        element,
        [
            # Placed from the City's own photographs, as Esri serves them since 2016…
            _contribution(element, "2019-01-01T00:00:00Z", 1, {"barrier": "kerb"}, creation=True),
            # …and its height surveyed on the street by a survey app.
            _contribution(element, "2023-01-01T00:00:00Z", 2, KERB_LOWERED, creation=False),
        ],
        [
            Changeset(
                1, "2019-01-01T00:00:00Z", None, 1, None, {"imagery_used": "Esri World Imagery"}
            ),
            Changeset(
                2, "2023-01-01T00:00:00Z", None, 1, None, {"created_by": "StreetComplete 51"}
            ),
        ],
    )

    found = scene.run(history=history)

    [row] = _rows(found, Topic.CURB_RAMP)
    assert row.lineage is LineageRelationship.APPARENTLY_INDEPENDENT
    assert row.target_geometry_lineage == str(LineageRelationship.POSSIBLE_SHARED)
    [osm_id] = row.osm_assertions
    assertion = found.assertions[osm_id]
    assert assertion.dates.osm_value_since == "2023-01-01T00:00:00Z"
    assert assertion.history.introducing_changeset == 2
    assert "survey" in assertion.history.stated_sources
    # A survey app records answers on the spot: its edit dates the observation.
    assert assertion.dates.observation_date == "2023-01-01"
    assert assertion.dates.observation_date_basis == SURVEY_APP_EDIT


def test_without_history_two_sided_rows_are_not_assessed_and_one_sided_not_applicable() -> None:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "asphalt"})
    scene.street.line(2, [(0, 51), (100, 51)], SIDEWALK)
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="ASPHALT", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    scene.add(
        _record(2, [(10, 50), (90, 50)], surface="ASPHALT", surface_state="non_default"),
        _matched(2, (_way("way/2", 10.0, 90.0),)),
    )

    found = scene.run()

    lineage = {r.relationship: r.lineage for r in found.reconciliations}
    assert lineage[Relationship.AGREEMENT] is LineageRelationship.NOT_ASSESSED
    assert lineage[Relationship.SOURCE_ONLY_KITCHENER] is LineageRelationship.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------


def _run_inputs(scene: Scene) -> RunInputs:
    index = scene.street.index()
    physical = KitchenerIndex.build(
        KitchenerFeature(r.activetransportid, "physical_active", r.network_role, "X", r.geometry)
        for r in scene.records.values()
    )
    records = list(scene.records.values())
    source = Source("s", "p", "d", ("pub",), "snap", None, "lic", None, "attr", "role")
    return RunInputs(
        conflation=ConflationInputs(
            osm=index,
            population=Population(records, {}, physical),
            eligible=physical,
            relationships=RelationshipIndex(physical, index.lines),
            parquet=Path("fixture.parquet"),
            identity={},
        ),
        geo05=Geo05Artifact(dict(scene.decisions), {}, "0" * 64),
        city_fields={i: _fields(r) for i, r in scene.records.items()},
        city_curb_cuts=KitchenerIndex.build([]),
        area=box(-10_000, -10_000, 10_000, 10_000),
        sources=[source],
        identity={},
    )


def _artifact_scene() -> Scene:
    scene = Scene()
    scene.street.line(1, [(0, 1), (100, 1)], {**SIDEWALK, "surface": "concrete"})
    kerb = scene.street.node(100, 1, KERB_LOWERED)
    scene.add(
        _record(1, [(10, 0), (90, 0)], surface="BRICK", surface_state="non_default"),
        _matched(1, (_way("way/1", 10.0, 90.0),)),
    )
    scene.add(
        _record(2, [(99, 0), (101, 0)], curb_cut=True),
        _matched(2, (Target(f"node/{kerb}", "kerb"),), rule="curb_cut_kerb_node"),
    )
    return scene


def test_the_same_inputs_write_byte_identical_tables(tmp_path: Path) -> None:
    written = []
    for name in ("first", "second"):
        run_inputs = _run_inputs(_artifact_scene())
        reconciled = run_reconciliation(run_inputs, None)
        written.append(write_reconciliation_artifact(tmp_path / name, run_inputs, reconciled))

    assert {k: v["sha256"] for k, v in written[0].items()} == {
        k: v["sha256"] for k, v in written[1].items()
    }
    assert set(written[0]) == {"sources", "assertions", "correspondences", "reconciliations"}


def test_the_evidence_counts_coverage_and_lists_every_conflict(tmp_path: Path) -> None:
    run_inputs = _run_inputs(_artifact_scene())
    reconciled = run_reconciliation(run_inputs, None)
    files = write_reconciliation_artifact(tmp_path, run_inputs, reconciled)

    document = reconciliation_evidence(run_inputs, reconciled, files, None)

    surface = document["coverage"]["surface"]
    assert surface["union"] == surface["baseline_osm"] + surface["kitchener_only"]
    [case] = document["conflict_casebook"]["cases"]
    assert case["kitchener"][0]["raw_value"] == "BRICK"
    assert case["osm"][0]["raw_value"] == "concrete"
    assert document["conflict_casebook"]["every_case"]["conflict"].startswith("unresolved")
    assert document["routing"]["eligible_rows"] == 0
