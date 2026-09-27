"""The label schema, repeat-label agreement, and the deterministic lineage rules.

Manual judgements are not tested here — only that a label file must fit its
definitions, and that the lineage rules say what they claim to say.
"""

from __future__ import annotations

from typing import Any

import pytest

from pathable_api.geo.kitchener.lineage import (
    Correspondence,
    ElementHistory,
    LabelError,
    Lineage,
    Signal,
    attribute_lineage,
    changeset_evidence,
    combine,
    geometry_lineage,
    parse_label,
    parse_labels,
    raw_agreement,
    signals_in_changeset_source,
    signals_in_comment,
    signals_in_imagery_used,
    signals_in_source,
)
from pathable_api.geo.kitchener.osm_history import Changeset, Contribution

CANDIDATES = ["way/1", "way/2", "node/9"]


def _label(**values: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "activetransportid": 5,
        "correspondence": "obvious_correspondence",
        "osm": ["way/1"],
        "representation": "separate_way",
        "relationship": "one_to_one",
        "geometry": "closely_aligned",
        "topology": "topology_agreement",
        "note": "",
    }
    item.update(values)
    return item


class TestLabels:
    def test_a_complete_label_parses(self) -> None:
        label = parse_label(_label(), CANDIDATES)

        assert label.correspondence is Correspondence.OBVIOUS
        assert label.as_dict()["relationship"] == "one_to_one"

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"osm": []}, "names at least one OSM way"),
            ({"osm": ["node/9"]}, "names at least one OSM way"),
            ({"relationship": None}, "needs a relationship"),
            ({"osm": ["way/3"]}, "not among its candidate ways or nearby nodes"),
            ({"correspondence": "mostly_matches"}, "mostly_matches"),
            (
                {"correspondence": "ambiguous_correspondence"},
                "only an obvious correspondence has a relationship",
            ),
            (
                {"correspondence": "no_correspondence", "relationship": None},
                "names no OSM way and no geometry class",
            ),
            (
                {
                    "correspondence": "not_comparable",
                    "relationship": None,
                    "osm": [],
                    "geometry": None,
                },
                "has no topology to assess",
            ),
        ],
    )
    def test_a_label_that_breaks_a_definition_is_refused(
        self, change: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(LabelError, match=message):
            parse_label(_label(**change), CANDIDATES)

    def test_an_ambiguous_label_may_cite_a_node(self) -> None:
        label = parse_label(
            _label(
                correspondence="ambiguous_correspondence",
                osm=["node/9"],
                representation="node",
                relationship=None,
                geometry=None,
            ),
            CANDIDATES,
        )

        assert label.osm == ("node/9",)

    def test_a_file_labels_each_sampled_record_once(self) -> None:
        document = {"kitchener_geo04_labels_version": 1, "records": [_label(), _label()]}

        with pytest.raises(LabelError, match="labelled twice"):
            parse_labels(document, {5: CANDIDATES})
        with pytest.raises(LabelError, match="not in the study sample"):
            parse_labels({**document, "records": [_label()]}, {6: CANDIDATES})
        with pytest.raises(LabelError, match="known version"):
            parse_labels({"records": []}, {5: CANDIDATES})


class TestAgreement:
    def test_raw_agreement_over_the_records_both_passes_labelled(self) -> None:
        first = {1: "obvious", 2: "obvious", 3: "ambiguous", 4: "none"}
        second = {1: "obvious", 2: "ambiguous", 3: "ambiguous", 5: "none"}

        result = raw_agreement(first, second)

        assert result["records"] == 3
        assert result["agree"] == 2
        assert result["raw_agreement"] == pytest.approx(0.667)
        assert result["matrix"] == {
            "ambiguous": {"ambiguous": 1},
            "obvious": {"ambiguous": 1, "obvious": 1},
        }
        assert result["disagreements"] == [
            {"activetransportid": 2, "first": "obvious", "second": "ambiguous"}
        ]


class TestSignals:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("City of Kitchener Open Data", {Signal.KITCHENER, Signal.IMPORT}),
            ("Kitchener orthophoto 2019", {Signal.PUBLIC_IMAGERY}),
            ("Region of Waterloo", {Signal.OTHER_GOVERNMENT}),
            ("Bing", {Signal.DECLARED_IMAGERY}),
            ("survey;Bing", {Signal.SURVEY, Signal.DECLARED_IMAGERY}),
            ("Mapillary", {Signal.STREET_LEVEL}),
            # Regression: word boundaries missed words joined by underscores.
            ("Geobase_Import_2009", {Signal.OTHER_GOVERNMENT, Signal.IMPORT}),
            ("Bing_2015", {Signal.DECLARED_IMAGERY}),
            ("City_of_Kitchener_2019", {Signal.KITCHENER}),
            ("NRCan-CanVec-8.0", {Signal.OTHER_GOVERNMENT}),
            ("Kitchenerville", set()),
            ("aerial imagery", {Signal.UNSPECIFIED_IMAGERY}),
            # The Region's orthophoto layer, which the City's ORTHO records may share.
            ("Region of Waterloo 2024", {Signal.PUBLIC_IMAGERY}),
            (
                "GRT GTFS; GRT Schedule; Region of Waterloo 2024; Bing",
                {Signal.PUBLIC_IMAGERY, Signal.DECLARED_IMAGERY},
            ),
        ],
    )
    def test_a_source_value_names_its_kind(self, value: str, expected: set[Signal]) -> None:
        assert signals_in_source(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (
                "Esri World Imagery;Mapillary Images;OpenStreetCam Images",
                {Signal.EDITOR_IMAGERY, Signal.EDITOR_STREET_LEVEL},
            ),
            (
                "Custom (https://gis.regionofwaterloo.ca/waimagery/services/Imagery_2024/"
                "ImageServer/WMSServer)",
                {Signal.PUBLIC_IMAGERY},
            ),
            ("Bing Maps Aerial;.gpx data file", {Signal.EDITOR_IMAGERY, Signal.EDITOR_GPS}),
            ("None", set()),
        ],
    )
    def test_an_editor_record_is_read_layer_by_layer(
        self, value: str, expected: set[Signal]
    ) -> None:
        assert signals_in_imagery_used(value) == expected

    def test_the_words_id_writes_itself_are_the_editors_not_the_mappers(self) -> None:
        written = "streetlevel imagery;mapillary;openstreetcam;aerial imagery"

        assert signals_in_changeset_source(written, editor="iD 2.20.1") == {
            Signal.EDITOR_STREET_LEVEL,
            Signal.UNSPECIFIED_IMAGERY,
        }
        assert Signal.SURVEY in signals_in_changeset_source(
            f"{written};local knowledge", editor="iD 2.20.1"
        )
        # Typed into another editor, the same words are the mapper's statement.
        assert signals_in_changeset_source(written, editor="JOSM/1.5 (18969 en)") == {
            Signal.STREET_LEVEL
        }

    def test_a_place_name_in_a_comment_is_not_a_source(self) -> None:
        assert signals_in_comment("Added sidewalks in Kitchener") == set()
        assert signals_in_comment("Kitchener open data sidewalks") >= {Signal.KITCHENER}
        assert signals_in_comment("Traced sidewalks in Kitchener from aerial imagery") == {
            Signal.PUBLIC_IMAGERY
        }

    def test_an_editor_imagery_record_is_not_a_mapper_declaration(self) -> None:
        changeset = Changeset(
            5,
            None,
            None,
            1,
            None,
            {"imagery_used": "Esri World Imagery", "created_by": "StreetComplete 57.1"},
        )

        signals = {e.signal for e in changeset_evidence(changeset)}

        assert signals == {Signal.EDITOR_IMAGERY, Signal.SURVEY}


def _contribution(
    changeset: int,
    timestamp: str,
    *,
    creation: bool = False,
    geometry: bool = False,
    tags: dict[str, str] | None = None,
) -> Contribution:
    return Contribution(
        element="way/1",
        timestamp=timestamp,
        version=1,
        changeset=changeset,
        creation=creation,
        deletion=False,
        geometry_change=geometry,
        tag_change=not creation and not geometry,
        tags=tags or {"highway": "footway"},
    )


def _history(*contributions: Contribution, complete: bool = True) -> ElementHistory:
    return ElementHistory("way/1", contributions, complete, None if complete else "ends early")


def _changesets(**tags_by_id: dict[str, str]) -> dict[int, Changeset]:
    return {
        int(key[1:]): Changeset(int(key[1:]), None, None, 1, None, tags)
        for key, tags in tags_by_id.items()
    }


class TestGeometryLineage:
    def test_a_stated_kitchener_source_is_known_derivation(self) -> None:
        history = _history(_contribution(1, "2020-01-01T00:00:00Z", creation=True))
        changesets = _changesets(c1={"source": "City of Kitchener open data"})

        finding = geometry_lineage(
            history, changesets, municipal_since=None, vertex_coincidence=False
        )

        assert finding.label is Lineage.KNOWN

    def test_no_stated_source_is_unknown_never_independent(self) -> None:
        # The rule the card insists on: absence of a municipal source is not
        # evidence of independence.
        history = _history(_contribution(1, "2020-01-01T00:00:00Z", creation=True))

        finding = geometry_lineage(
            history, _changesets(c1={}), municipal_since=None, vertex_coincidence=False
        )

        assert finding.label is Lineage.UNKNOWN
        assert finding.reasons == ("no contribution states a source",)

    def test_every_shaping_edit_must_state_an_unrelated_source(self) -> None:
        history = _history(
            _contribution(1, "2012-01-01T00:00:00Z", creation=True),
            _contribution(2, "2016-01-01T00:00:00Z", geometry=True),
            _contribution(3, "2018-01-01T00:00:00Z"),  # tags only: not a shaping edit
        )
        both = _changesets(c1={"source": "Bing"}, c2={"source": "survey"}, c3={})
        one = _changesets(c1={"source": "Bing"}, c2={}, c3={})

        found = geometry_lineage(history, both, municipal_since=None, vertex_coincidence=False)
        assert found.label is Lineage.INDEPENDENT
        assert found.basis == "declared"  # both sources typed by the mapper
        partial = geometry_lineage(history, one, municipal_since=None, vertex_coincidence=False)
        assert partial.label is Lineage.UNKNOWN
        assert any("others state none" in note for note in partial.notes)

    def test_shared_vertices_make_it_possible_shared_lineage(self) -> None:
        history = _history(_contribution(1, "2020-01-01T00:00:00Z", creation=True))
        changesets = _changesets(c1={"source": "Bing"})

        finding = geometry_lineage(
            history, changesets, municipal_since=None, vertex_coincidence=True
        )

        assert finding.label is Lineage.POSSIBLE

    def test_a_shape_older_than_the_citys_record_is_independent(self) -> None:
        history = _history(_contribution(1, "2009-05-01T00:00:00Z", creation=True))

        finding = geometry_lineage(
            history, _changesets(c1={}), municipal_since="2012-03-31", vertex_coincidence=False
        )

        assert finding.label is Lineage.INDEPENDENT
        assert "predates" in finding.reasons[0]

    def test_a_declared_source_outranks_a_date_as_the_basis(self) -> None:
        # Bug: a shape a mapper declared surveyed was reported as resting on dates,
        # the weaker evidence, because it also predated the City's record.
        history = _history(_contribution(1, "2009-05-01T00:00:00Z", creation=True))

        finding = geometry_lineage(
            history,
            _changesets(c1={"source": "survey"}),
            municipal_since="2012-03-31",
            vertex_coincidence=False,
        )

        assert finding.label is Lineage.INDEPENDENT
        assert finding.basis == "declared"

    def test_history_that_stops_short_cannot_show_independence(self) -> None:
        history = _history(_contribution(1, "2012-01-01T00:00:00Z", creation=True), complete=False)

        finding = geometry_lineage(
            history,
            _changesets(c1={"source": "survey"}),
            municipal_since=None,
            vertex_coincidence=False,
        )

        assert finding.label is Lineage.UNKNOWN
        assert "ends early" in finding.notes

    def test_an_element_source_tag_counts_only_for_the_edit_that_wrote_it(self) -> None:
        tagged = {"highway": "footway", "source": "City of Kitchener"}
        history = _history(
            _contribution(1, "2012-01-01T00:00:00Z", creation=True),
            _contribution(2, "2014-01-01T00:00:00Z", tags=tagged),  # tag edit, not shaping
            _contribution(3, "2016-01-01T00:00:00Z", geometry=True, tags=tagged),
        )

        finding = geometry_lineage(
            history,
            _changesets(c1={}, c2={}, c3={}),
            municipal_since=None,
            vertex_coincidence=False,
        )

        assert finding.label is Lineage.UNKNOWN


class TestAttributeLineage:
    def test_a_kerb_from_a_survey_app_is_independent(self) -> None:
        history = _history(
            _contribution(1, "2015-01-01T00:00:00Z", creation=True),
            _contribution(2, "2023-01-01T00:00:00Z", tags={"kerb": "lowered"}),
        )
        changesets = _changesets(
            c1={}, c2={"created_by": "StreetComplete 50.2", "source": "survey"}
        )

        finding = attribute_lineage(history, changesets, "kerb", municipal_since=None)

        assert finding is not None
        assert finding.label is Lineage.INDEPENDENT
        assert finding.steps[0].changeset == 2

    def test_editor_imagery_does_not_vouch_for_a_kerb_but_does_for_a_surface(self) -> None:
        history = _history(
            _contribution(
                1,
                "2020-01-01T00:00:00Z",
                creation=True,
                tags={"kerb": "lowered", "surface": "asphalt"},
            )
        )
        changesets = _changesets(c1={"imagery_used": "Bing Maps Aerial"})

        kerb = attribute_lineage(history, changesets, "kerb", municipal_since=None)
        surface = attribute_lineage(history, changesets, "surface", municipal_since=None)

        assert kerb is not None
        assert surface is not None
        assert kerb.label is Lineage.UNKNOWN
        assert surface.label is Lineage.INDEPENDENT
        assert "introduced in the same contribution as the geometry it sits on" in surface.notes

    def test_street_level_photos_on_screen_vouch_for_a_kerb_as_an_editor_record(self) -> None:
        history = _history(
            _contribution(1, "2020-01-01T00:00:00Z", creation=True, tags={"kerb": "lowered"})
        )
        changesets = _changesets(
            c1={"imagery_used": "Bing Maps Aerial;Mapillary Images", "created_by": "iD 2.27.0"}
        )

        finding = attribute_lineage(history, changesets, "kerb", municipal_since=None)

        assert finding is not None
        assert finding.label is Lineage.INDEPENDENT
        assert finding.basis == "editor_recorded"

    def test_a_frozen_value_the_history_never_reached_is_unknown(self) -> None:
        # Bug: a value changed after the history ends was traced as if it were
        # the frozen one, so the lineage described an older value.
        history = _history(
            _contribution(1, "2020-01-01T00:00:00Z", creation=True, tags={"kerb": "raised"}),
            complete=False,
        )
        changesets = _changesets(c1={"source": "survey"})

        finding = attribute_lineage(
            history, changesets, "kerb", municipal_since=None, frozen_value="lowered"
        )
        traced = attribute_lineage(
            history, changesets, "kerb", municipal_since=None, frozen_value="raised"
        )

        assert finding is not None
        assert finding.label is Lineage.UNKNOWN
        assert finding.reasons == ("the frozen value is not in the element's history",)
        assert traced is not None
        assert traced.steps

    def test_no_value_no_finding(self) -> None:
        history = _history(_contribution(1, "2020-01-01T00:00:00Z", creation=True))

        assert attribute_lineage(history, _changesets(c1={}), "kerb", municipal_since=None) is None


def test_the_least_independent_lineage_wins() -> None:
    assert combine([Lineage.INDEPENDENT, Lineage.UNKNOWN]) is Lineage.UNKNOWN
    assert combine([Lineage.INDEPENDENT, Lineage.POSSIBLE, Lineage.UNKNOWN]) is Lineage.POSSIBLE
    assert combine([Lineage.KNOWN, Lineage.INDEPENDENT]) is Lineage.KNOWN
    assert combine([]) is None
