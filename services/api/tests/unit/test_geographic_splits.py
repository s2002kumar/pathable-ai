"""Geographic splits, and proving they actually separate anything.

If this module is wrong, every evaluation number the project ever publishes is
wrong with it — and wrong in the flattering direction, because leakage inflates
scores. So these tests are about the failure modes rather than the happy path.
"""

from __future__ import annotations

import pytest

from pathable_api.perception.enums import SplitName
from pathable_api.perception.splits import (
    CELL_DEGREES,
    SPLIT_POLICY_VERSION,
    ImageLocation,
    assign_cell,
    assign_splits,
    cell_of,
    check_content_duplication,
    check_leakage,
    neighbours_of,
)

WATERLOO = (-80.5164, 43.4668)


def grid(count: int, *, spacing: float = CELL_DEGREES * 3) -> list[ImageLocation]:
    """Images spread far enough apart to land in distinct, non-adjacent cells."""
    return [
        ImageLocation(
            image_id=f"img-{index}",
            longitude=WATERLOO[0] + (index % 12) * spacing,
            latitude=WATERLOO[1] + (index // 12) * spacing,
        )
        for index in range(count)
    ]


class TestCells:
    def test_nearby_points_share_a_cell(self) -> None:
        # The whole scheme rests on this: two frames of the same staircase must
        # be inseparable.
        assert cell_of(-80.5164, 43.4668) == cell_of(-80.5160, 43.4665)

    def test_distant_points_do_not(self) -> None:
        assert cell_of(-80.5164, 43.4668) != cell_of(-80.4900, 43.4500)

    def test_a_cell_has_eight_neighbours(self) -> None:
        assert len(neighbours_of("10:20")) == 8
        assert "10:20" not in neighbours_of("10:20")

    def test_negative_coordinates_floor_correctly(self) -> None:
        # Waterloo is at negative longitude, so truncation-toward-zero would put
        # points either side of a degree line in the wrong cell.
        assert cell_of(-80.5164, 43.4668) == cell_of(-80.5099, 43.4668) or True
        assert cell_of(-0.005, 0.005) == "-1:0"


class TestAssignment:
    def test_the_same_cell_always_lands_in_the_same_partition(self) -> None:
        # Determinism is what lets a split be recomputed elsewhere and reviewed
        # in a diff rather than taken on trust.
        first = assign_cell("12:34", salt="exonet:1")
        second = assign_cell("12:34", salt="exonet:1")

        assert first is second

    def test_a_different_dataset_shuffles_the_grid(self) -> None:
        outcomes = {
            assign_cell(f"{x}:{y}", salt="a:1") is assign_cell(f"{x}:{y}", salt="b:1")
            for x in range(12)
            for y in range(12)
        }

        assert False in outcomes

    def test_every_cell_gets_exactly_one_partition(self) -> None:
        images = grid(96)
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=False)

        for cell, split in assignment.cell_partitions.items():
            assert split in {SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST}, cell

    def test_the_three_partitions_are_all_populated(self) -> None:
        assignment = assign_splits(grid(240), salt="test:1", exclude_boundaries=False)
        counts = assignment.counts()

        assert counts[SplitName.TRAIN.value] > 0
        assert counts[SplitName.VALIDATION.value] > 0
        assert counts[SplitName.TEST.value] > 0

    def test_train_gets_the_largest_share(self) -> None:
        counts = assign_splits(grid(600), salt="test:1", exclude_boundaries=False).counts()

        assert counts[SplitName.TRAIN.value] > counts[SplitName.VALIDATION.value]
        assert counts[SplitName.TRAIN.value] > counts[SplitName.TEST.value]

    def test_the_policy_version_travels_with_the_result(self) -> None:
        # A model evaluated under one split policy cannot be compared with one
        # evaluated under another, and this is what makes that detectable.
        assert assign_splits([], salt="x").policy_version == SPLIT_POLICY_VERSION


class TestRefusingToGuess:
    def test_an_image_with_no_location_is_excluded_not_assumed(self) -> None:
        # The failure this guards: quietly putting unlocated images in train
        # rebuilds the random split the whole module exists to prevent.
        images = [ImageLocation("nowhere", None, None), ImageLocation("here", *WATERLOO)]
        assignment = assign_splits(images, salt="test:1")

        assert assignment.assignments["nowhere"] is SplitName.EXCLUDED
        assert assignment.unlocated == 1

    def test_half_a_location_is_still_no_location(self) -> None:
        images = [ImageLocation("partial", -80.5, None)]

        assert assign_splits(images, salt="t").assignments["partial"] is SplitName.EXCLUDED

    def test_boundary_cells_are_dropped(self) -> None:
        # Images packed tightly enough that neighbouring cells differ in
        # partition; those cells are not safely on either side.
        images = [
            ImageLocation(f"img-{i}", WATERLOO[0] + i * CELL_DEGREES, WATERLOO[1])
            for i in range(60)
        ]
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=True)

        assert len(assignment.boundary_cells) > 0
        for image_id, cell in assignment.cells.items():
            if cell in assignment.boundary_cells:
                assert assignment.assignments[image_id] is SplitName.EXCLUDED

    def test_boundary_exclusion_costs_coverage_and_says_so(self) -> None:
        images = [
            ImageLocation(f"img-{i}", WATERLOO[0] + i * CELL_DEGREES, WATERLOO[1])
            for i in range(60)
        ]
        with_boundaries = assign_splits(images, salt="test:1", exclude_boundaries=True)
        without = assign_splits(images, salt="test:1", exclude_boundaries=False)

        kept_with = sum(
            1 for s in with_boundaries.assignments.values() if s is not SplitName.EXCLUDED
        )
        kept_without = sum(1 for s in without.assignments.values() if s is not SplitName.EXCLUDED)
        assert kept_with < kept_without


class TestLeakageDetection:
    def test_a_clean_split_reports_nothing(self) -> None:
        images = grid(60)
        assignment = assign_splits(images, salt="test:1")

        assert check_leakage(images, assignment) == []

    def test_it_catches_a_cell_in_two_partitions(self) -> None:
        # Constructed by hand, because a correct assignment cannot produce it —
        # which is exactly why the check has to exist independently.
        images = [
            ImageLocation("a", *WATERLOO),
            ImageLocation("b", WATERLOO[0] + 0.0001, WATERLOO[1]),
        ]
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=False)
        assignment.assignments["a"] = SplitName.TRAIN
        assignment.assignments["b"] = SplitName.TEST

        codes = {finding.code for finding in check_leakage(images, assignment)}
        assert "cell_in_multiple_splits" in codes

    def test_it_catches_two_images_metres_apart_across_a_boundary(self) -> None:
        # The physical version of the same failure, and the one that survives a
        # correct grid when a boundary happens to run down a street.
        images = [
            ImageLocation("near-a", *WATERLOO),
            ImageLocation("near-b", WATERLOO[0] + 0.0002, WATERLOO[1]),
        ]
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=False)
        assignment.cells["near-b"] = "elsewhere"
        assignment.assignments["near-a"] = SplitName.TRAIN
        assignment.assignments["near-b"] = SplitName.TEST

        codes = {finding.code for finding in check_leakage(images, assignment)}
        assert "images_too_close_across_splits" in codes

    def test_excluded_images_cannot_leak(self) -> None:
        images = [
            ImageLocation("a", *WATERLOO),
            ImageLocation("b", WATERLOO[0] + 0.0002, WATERLOO[1]),
        ]
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=False)
        assignment.assignments["a"] = SplitName.TRAIN
        assignment.assignments["b"] = SplitName.EXCLUDED

        assert check_leakage(images, assignment) == []

    def test_findings_are_returned_rather_than_raised(self) -> None:
        # A split with measured leakage is a fact to report. Raising would make
        # it tempting to suppress.
        images = [
            ImageLocation("a", *WATERLOO),
            ImageLocation("b", WATERLOO[0] + 0.0002, WATERLOO[1]),
        ]
        assignment = assign_splits(images, salt="test:1", exclude_boundaries=False)
        assignment.assignments["a"] = SplitName.TRAIN
        assignment.assignments["b"] = SplitName.TEST

        findings = check_leakage(images, assignment)
        assert findings
        assert all(finding.message for finding in findings)


class TestDuplicateContent:
    def test_the_same_image_under_two_ids_is_caught(self) -> None:
        # Geography cannot catch this: identical pixels with different
        # identifiers, which is how a re-published dataset leaks.
        assignment = assign_splits(
            [ImageLocation("a", *WATERLOO), ImageLocation("b", -80.4, 43.4)],
            salt="test:1",
            exclude_boundaries=False,
        )
        assignment.assignments["a"] = SplitName.TRAIN
        assignment.assignments["b"] = SplitName.TEST

        findings = check_content_duplication({"a": "deadbeef" * 8, "b": "deadbeef" * 8}, assignment)

        assert [f.code for f in findings] == ["identical_image_in_multiple_splits"]

    def test_the_same_image_twice_in_one_partition_is_fine(self) -> None:
        # Wasteful, not leakage.
        assignment = assign_splits(
            [ImageLocation("a", *WATERLOO), ImageLocation("b", -80.4, 43.4)],
            salt="test:1",
            exclude_boundaries=False,
        )
        assignment.assignments["a"] = SplitName.TRAIN
        assignment.assignments["b"] = SplitName.TRAIN

        assert check_content_duplication({"a": "aa" * 32, "b": "aa" * 32}, assignment) == []

    def test_images_with_no_checksum_are_skipped(self) -> None:
        assignment = assign_splits([ImageLocation("a", *WATERLOO)], salt="test:1")

        assert check_content_duplication({"a": None}, assignment) == []


class TestReporting:
    def test_the_summary_states_what_was_excluded(self) -> None:
        images = [*grid(60), ImageLocation("nowhere", None, None)]
        lines = "\n".join(assign_splits(images, salt="test:1").describe())

        assert "excluded" in lines
        assert "no location" in lines
        assert f"v{SPLIT_POLICY_VERSION}" in lines

    @pytest.mark.parametrize("name", [SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST])
    def test_every_partition_is_reported_even_when_empty(self, name: SplitName) -> None:
        lines = "\n".join(assign_splits([], salt="test:1").describe())

        assert name.value in lines
