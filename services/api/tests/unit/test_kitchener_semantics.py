"""What a Kitchener value means: never let null, unknown and a template default merge.

These are the rules the whole audit rests on. A test here fails if a default
is counted as evidence, if a virtual link is counted as physical, or if a
personal name could reach committed evidence.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.kitchener.semantics import (
    FieldSchema,
    FieldState,
    Lifecycle,
    NetworkRole,
    Origin,
    PhysicalClass,
    SourceClass,
    field_state,
    lifecycle,
    network_role,
    physical_class,
    source_class,
    source_year,
    update_account,
    value_origin,
)

SURFACE = FieldSchema(
    "SURFACE_MATERIAL",
    "esriFieldTypeString",
    "CONCRETE",
    frozenset({"ASPHALT", "CONCRETE", "UNKNOWN", "NA (VIRTUAL LINK)"}),
)
WIDTH = FieldSchema("WIDTH_M", "esriFieldTypeDouble", 1.5, frozenset({0, 1.5, 2, 3.5}))
CURBCUT = FieldSchema("CURBCUT", "esriFieldTypeString", "N", frozenset({"Y", "N", "U"}))
YEAR = FieldSchema("LAST_INSPECTION_YEAR", "esriFieldTypeString", None, None)


class TestFieldState:
    @pytest.mark.parametrize(
        ("schema", "value", "expected"),
        [
            (SURFACE, None, FieldState.NULL),
            (SURFACE, "  ", FieldState.BLANK),
            (SURFACE, "UNKNOWN", FieldState.UNKNOWN),
            (SURFACE, "NA (VIRTUAL LINK)", FieldState.NOT_APPLICABLE),
            (SURFACE, "CONCRETE", FieldState.TEMPLATE_DEFAULT),
            (SURFACE, "ASPHALT", FieldState.NON_DEFAULT),
            (SURFACE, "GRANITE", FieldState.OUT_OF_DOMAIN),
            (CURBCUT, "U", FieldState.UNKNOWN),
            (CURBCUT, "N", FieldState.TEMPLATE_DEFAULT),
            (CURBCUT, "Y", FieldState.NON_DEFAULT),
            (WIDTH, 1.5, FieldState.TEMPLATE_DEFAULT),
            (WIDTH, 1, FieldState.OUT_OF_DOMAIN),
            (WIDTH, 0, FieldState.NON_DEFAULT),
            (YEAR, "2026", FieldState.NON_DEFAULT),
        ],
    )
    def test_every_state_is_kept_apart(
        self, schema: FieldSchema, value: object, expected: FieldState
    ) -> None:
        assert field_state(schema, value) is expected

    def test_a_field_the_publication_does_not_carry_is_not_published_not_null(self) -> None:
        assert field_state(CURBCUT, None, published=False) is FieldState.NOT_PUBLISHED
        assert field_state(None, "Y") is FieldState.NOT_PUBLISHED

    def test_a_default_never_counts_as_an_observation(self) -> None:
        assert (
            value_origin("SURFACE_MATERIAL", FieldState.TEMPLATE_DEFAULT) is Origin.TEMPLATE_DEFAULT
        )
        assert value_origin("CURBCUT", FieldState.UNKNOWN) is Origin.UNKNOWN
        assert value_origin("CURBCUT", FieldState.NULL) is Origin.UNKNOWN


class TestOrigin:
    def test_documented_origins_follow_the_citys_own_words(self) -> None:
        # GRADE is "calculated through a script": derived, whatever its value.
        assert value_origin("GRADE", FieldState.NON_DEFAULT) is Origin.DERIVED
        assert value_origin("SLOPE_GRADIENT_PERCENT", FieldState.NON_DEFAULT) is Origin.DERIVED
        # Condition is "as found in the 2015 Trail inventory project".
        assert value_origin("SURFACE_CONDITION", FieldState.NON_DEFAULT) is Origin.OBSERVED_SURVEY
        assert value_origin("LAST_INSPECTION_YEAR", FieldState.NON_DEFAULT) is Origin.OBSERVED_EVENT
        assert value_origin("CURBCUT", FieldState.NON_DEFAULT) is Origin.ADMINISTRATIVE_ASSERTION

    def test_what_the_documentation_does_not_explain_stays_unresolved(self) -> None:
        assert value_origin("GRADE_CATEGORY_MAX", FieldState.NON_DEFAULT) is Origin.UNRESOLVED
        assert value_origin("SOC_AAA", FieldState.NON_DEFAULT) is Origin.UNRESOLVED
        assert value_origin("SURFACE_MATERIAL", FieldState.OUT_OF_DOMAIN) is Origin.UNRESOLVED


class TestNetworkRole:
    def test_links_are_virtual_whatever_category_they_are_filed_under(self) -> None:
        filed_oddly = network_role("CYCLING", "LINK (PEDESTRIAN)", "NA (VIRTUAL LINK)", None)

        assert filed_oddly.role is NetworkRole.VIRTUAL_LINK
        assert filed_oddly.note is not None

    def test_a_physical_subcategory_with_a_virtual_code_is_unresolved_never_physical(
        self,
    ) -> None:
        decision = network_role("SIDEWALKS AND WALKWAYS", "CROSSWALK", "NA (VIRTUAL LINK)", None)

        assert decision.role is NetworkRole.UNRESOLVED
        assert physical_class(decision.role, Lifecycle.ACTIVE) is PhysicalClass.UNRESOLVED

    def test_a_crosswalk_filed_as_a_network_link_is_unresolved(self) -> None:
        decision = network_role("NETWORK LINKS", "CROSSWALK", "SURFACE", "CONCRETE")

        assert decision.role is NetworkRole.UNRESOLVED

    def test_connections_carry_the_virtual_code_and_stay_connections(self) -> None:
        # Found on the real snapshot: every driveway and on-road connection is
        # coded NA (VIRTUAL LINK). That is how the City codes them, not a conflict.
        decision = network_role(
            "NETWORK LINKS", "DRIVEWAY CONNECTION", "NA (VIRTUAL LINK)", "NA (VIRTUAL LINK)"
        )

        assert decision.role is NetworkRole.UNOFFICIAL_CONNECTION
        assert decision.note == "virtual code in feature_type, surface_material"

    def test_a_category_mismatch_between_physical_kinds_is_a_note_not_a_doubt(self) -> None:
        decision = network_role("SIDEWALKS AND WALKWAYS", "MINOR TRAIL", "SURFACE", "NATURAL")

        assert decision.role is NetworkRole.PEDESTRIAN_WAY
        assert (
            decision.note
            == "subcategory 'MINOR TRAIL' filed under category 'SIDEWALKS AND WALKWAYS'"
        )

    def test_crossrides_are_not_counted_as_pedestrian_crossings(self) -> None:
        assert (
            network_role("PATHWAYS", "MIXED CROSSRIDE", "SURFACE", "ASPHALT (PAINTED)").role
            is NetworkRole.CYCLING_CROSSING
        )


class TestPhysicalClass:
    def test_lifecycle_comes_first(self) -> None:
        assert physical_class(NetworkRole.VIRTUAL_LINK, Lifecycle.CLOSED) is PhysicalClass.CLOSED
        assert (
            physical_class(NetworkRole.PEDESTRIAN_WAY, Lifecycle.POTENTIAL) is PhysicalClass.PLANNED
        )
        assert (
            physical_class(NetworkRole.PEDESTRIAN_WAY, Lifecycle.UNDESIGNATED)
            is PhysicalClass.UNRESOLVED
        )

    def test_a_physical_record_without_a_published_status_says_so(self) -> None:
        state = lifecycle(None, published=False)

        assert state is Lifecycle.NOT_PUBLISHED
        assert (
            physical_class(NetworkRole.PEDESTRIAN_WAY, state)
            is PhysicalClass.PHYSICAL_STATUS_NOT_PUBLISHED
        )

    def test_a_virtual_link_is_never_physical(self) -> None:
        for state in (Lifecycle.ACTIVE, Lifecycle.NOT_PUBLISHED):
            assert physical_class(NetworkRole.VIRTUAL_LINK, state) is PhysicalClass.VIRTUAL_LINK


class TestSourceVocabulary:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("ORTHO 2012", SourceClass.ORTHOIMAGERY),
            ("SPRING 2023 ORTHO", SourceClass.ORTHOIMAGERY),
            ("2015 TRAIL INVENTORY PROJECT", SourceClass.TRAIL_INVENTORY_2015),
            ("PLAN AND PROFILE 441384-441388", SourceClass.ENGINEERING_PLAN),
            ("SP19038CES", SourceClass.ENGINEERING_PLAN),
            ("ENGINEERING STAFF - TO BE VERIFIED", SourceClass.STAFF_ASSERTION),
            ("PERSONAL OBSERVATION -JT", SourceClass.PERSONAL_OBSERVATION),
            ("GOOGLE STREETVIEW", SourceClass.STREET_LEVEL_IMAGERY),
            ("SIDEWALK PRIORITY PROJECT", SourceClass.PROJECT_OR_PROGRAMME),
            ("TO INPUT", SourceClass.PLACEHOLDER),
            ("A. Person", SourceClass.OTHER),
            (None, SourceClass.NULL),
        ],
    )
    def test_source_values_are_classed(self, value: str | None, expected: SourceClass) -> None:
        assert source_class(value) is expected

    def test_only_orthoimagery_names_a_capture_year(self) -> None:
        assert source_year("ORTHO 2025 SPRING") == 2025
        assert source_year("PILOT PROJECT 2019") is None

    def test_named_accounts_are_reduced_before_leaving_the_snapshot(self) -> None:
        assert update_account("GIS_DATA") == "GIS_DATA"
        assert update_account("JDOE") == "named_account"
        assert update_account(None) is None
