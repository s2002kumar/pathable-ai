"""How a City value and an OSM value relate: agreement, compatible, conflict, incomparable.

Every pair here is a claim the reconciliation makes about real data, so each
is pinned. The rule the tests protect: equivalence stays narrow, a City curb
cut never becomes a kerb height, and an unrecognised value is never silently
an agreement or a conflict.
"""

from __future__ import annotations

import pytest

from pathable_api.geo.kitchener.assertions import Relationship as Rel
from pathable_api.geo.kitchener.assertions import Specificity as Spec
from pathable_api.geo.kitchener.reconciliation_vocabulary import (
    relate_curb,
    relate_railing,
    relate_structure,
    relate_surface,
)


@pytest.mark.parametrize(
    ("city", "osm", "relationship", "specificity"),
    [
        ("ASPHALT", "asphalt", Rel.AGREEMENT, Spec.SAME_LEVEL),
        # Paint is a marking; the material is still asphalt.
        ("ASPHALT (PAINTED)", "asphalt", Rel.AGREEMENT, Spec.SAME_LEVEL),
        # OSM says only "paved": consistent, not the same claim.
        ("ASPHALT", "paved", Rel.COMPATIBLE, Spec.KITCHENER_MORE_SPECIFIC),
        ("STONEDUST", "unpaved", Rel.COMPATIBLE, Spec.KITCHENER_MORE_SPECIFIC),
        ("NATURAL", "dirt", Rel.COMPATIBLE, Spec.OSM_MORE_SPECIFIC),
        ("BRICK", "paving_stones", Rel.COMPATIBLE, Spec.OVERLAPPING),
        ("STONEDUST", "compacted", Rel.COMPATIBLE, Spec.OVERLAPPING),
        ("STEEL", "metal", Rel.COMPATIBLE, Spec.KITCHENER_MORE_SPECIFIC),
        ("BRICK", "concrete", Rel.CONFLICT, Spec.SAME_LEVEL),
        ("ASPHALT", "concrete", Rel.CONFLICT, Spec.SAME_LEVEL),
        ("STONEDUST", "gravel", Rel.CONFLICT, Spec.SAME_LEVEL),
        ("ASPHALT", "unpaved", Rel.CONFLICT, Spec.KITCHENER_MORE_SPECIFIC),
        ("ASPHALT", None, Rel.SOURCE_ONLY_KITCHENER, Spec.NOT_APPLICABLE),
        (None, "asphalt", Rel.SOURCE_ONLY_OSM, Spec.NOT_APPLICABLE),
        (None, None, Rel.UNKNOWN, Spec.NOT_APPLICABLE),
    ],
)
def test_surface_pairs(
    city: str | None, osm: str | None, relationship: Rel, specificity: Spec
) -> None:
    found = relate_surface(city, osm)

    assert (found.relationship, found.specificity) == (relationship, specificity)


@pytest.mark.parametrize("osm", ["asphalt;concrete", "asphalt,concrete", "astroturf-ish"])
def test_a_surface_the_vocabulary_cannot_read_is_incomparable_never_a_conflict(osm: str) -> None:
    assert relate_surface("ASPHALT", osm).relationship is Rel.INCOMPARABLE


def test_osm_surface_values_are_read_case_insensitively_but_not_loosely() -> None:
    assert relate_surface("ASPHALT", " Asphalt ").relationship is Rel.AGREEMENT
    assert relate_surface("ASPHALT", "asphalt_concrete").relationship is Rel.INCOMPARABLE


@pytest.mark.parametrize(
    ("tags", "relationship"),
    [
        # A ramp's presence and a kerb's height: consistent, not the same property.
        ({"barrier": "kerb", "kerb": "lowered"}, Rel.COMPATIBLE),
        ({"barrier": "kerb", "kerb": "flush"}, Rel.COMPATIBLE),
        # OSM records a kerb but not its height: only the City says a ramp exists.
        ({"barrier": "kerb"}, Rel.SOURCE_ONLY_KITCHENER),
        ({"kerb": "yes"}, Rel.SOURCE_ONLY_KITCHENER),
        ({"barrier": "kerb", "kerb": "raised"}, Rel.CONFLICT),
        # Not wheelchair-traversable: not "a curbcut down to street level".
        ({"barrier": "kerb", "kerb": "rolled"}, Rel.CONFLICT),
        # No kerb at all: the City's curb cut presupposes one.
        ({"kerb": "no"}, Rel.INCOMPARABLE),
        ({"kerb": "slightly_bumpy"}, Rel.INCOMPARABLE),
    ],
)
def test_a_city_curb_cut_beside_each_osm_kerb(tags: dict[str, str], relationship: Rel) -> None:
    found = relate_curb(True, tags)

    assert found.relationship is relationship
    if relationship is Rel.COMPATIBLE:
        assert found.specificity is Spec.DIFFERENT_PROPERTY


def test_a_curb_cut_is_never_read_as_agreeing_with_a_kerb_height() -> None:
    # CURBCUT = Y states a ramp exists. It is not synonymous with lowered or flush.
    for kerb in ("lowered", "flush", "no", "raised", "rolled", "yes"):
        assert relate_curb(True, {"kerb": kerb}).relationship is not Rel.AGREEMENT


@pytest.mark.parametrize(
    ("tags", "relationship"),
    [
        ({"barrier": "kerb", "kerb": "lowered"}, Rel.SOURCE_ONLY_OSM),
        ({"barrier": "kerb", "kerb": "raised"}, Rel.SOURCE_ONLY_OSM),
        # Neither source states a ramp or a kerb's form.
        ({"barrier": "kerb"}, Rel.UNKNOWN),
    ],
)
def test_an_osm_kerb_where_the_city_records_no_curb_cut(
    tags: dict[str, str], relationship: Rel
) -> None:
    # CURBCUT = N never means "no curb cut", so this is never a conflict.
    assert relate_curb(False, tags).relationship is relationship


@pytest.mark.parametrize(
    ("city", "family", "osm", "relationship", "specificity"),
    [
        ("STAIRS", "steps", "steps", Rel.AGREEMENT, Spec.SAME_LEVEL),
        ("BRIDGE", "bridge", "yes", Rel.AGREEMENT, Spec.SAME_LEVEL),
        ("BRIDGE", "bridge", "boardwalk", Rel.COMPATIBLE, Spec.OSM_MORE_SPECIFIC),
        ("OVERPASS", "bridge", "yes", Rel.COMPATIBLE, Spec.KITCHENER_MORE_SPECIFIC),
        ("BOARDWALK", "bridge", "boardwalk", Rel.AGREEMENT, Spec.SAME_LEVEL),
        ("UNDERPASS", "tunnel", "yes", Rel.AGREEMENT, Spec.SAME_LEVEL),
        ("UNDERPASS", "tunnel", "building_passage", Rel.INCOMPARABLE, Spec.DIFFERENT_PROPERTY),
        # A structure only one source records.
        (None, "steps", "steps", Rel.SOURCE_ONLY_OSM, Spec.NOT_APPLICABLE),
        ("STAIRS", "steps", None, Rel.SOURCE_ONLY_KITCHENER, Spec.NOT_APPLICABLE),
        # A City STAIRS says nothing about whether the steps are on a bridge.
        ("STAIRS", "bridge", "yes", Rel.SOURCE_ONLY_OSM, Spec.NOT_APPLICABLE),
    ],
)
def test_structure_pairs(
    city: str | None, family: str, osm: str | None, relationship: Rel, specificity: Spec
) -> None:
    found = relate_structure(city, family, osm)

    assert (found.relationship, found.specificity) == (relationship, specificity)


def test_a_handrail_is_a_railing_but_handrail_no_does_not_contradict_one() -> None:
    assert relate_railing(True, ["yes"]).relationship is Rel.COMPATIBLE
    assert relate_railing(True, ["no"]).relationship is Rel.INCOMPARABLE
    assert relate_railing(True, []).relationship is Rel.SOURCE_ONLY_KITCHENER
    assert relate_railing(False, ["yes"]).relationship is Rel.SOURCE_ONLY_OSM
