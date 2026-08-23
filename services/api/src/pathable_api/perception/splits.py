"""Geographic train/validation/test splits, and the check that they hold.

A random split of street imagery does not measure generalisation. Adjacent frames
of the same staircase, taken seconds apart, land on both sides of the boundary,
and the model is scored on pictures it has effectively already seen. The number
that comes out is real arithmetic on a meaningless question.

So the split is assigned to **place**, not to image. Every located image falls in
a grid cell; every cell belongs to exactly one partition; and two images can only
be separated if they are geographically separated. A staircase cannot straddle
the boundary because a cell cannot.

Two consequences that are features rather than compromises:

**An image with no location cannot be split honestly**, so it is excluded rather
than guessed into the training set. Most public datasets do not geolocate, and
pretending otherwise would silently rebuild the random split this module exists
to prevent.

**Cells adjacent to a boundary are excluded too.** A cell is 0.01° — roughly
800 m by 1.1 km here — and a camera near its edge sees across it. Dropping one
ring of cells around each partition costs coverage and buys the only thing that
makes a test score mean anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pathable_api.perception.enums import SplitName

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

#: Bumped when a change here would move an image between partitions. A model
#: evaluated under one split version cannot be compared with one evaluated under
#: another, and this is what makes that detectable.
SPLIT_POLICY_VERSION = 1

#: Grid resolution in degrees. About 800 m east-west and 1.1 km north-south at
#: this latitude — large enough that a single street scene sits inside one cell,
#: small enough that a city yields enough cells to partition.
CELL_DEGREES = 0.01

#: Target share of cells per partition. Approximate by construction: cells are
#: assigned by hash, so the realised shares vary and are reported rather than
#: forced.
DEFAULT_RATIOS: dict[SplitName, float] = {
    SplitName.TRAIN: 0.70,
    SplitName.VALIDATION: 0.15,
    SplitName.TEST: 0.15,
}


def cell_of(longitude: float, latitude: float, *, size: float = CELL_DEGREES) -> str:
    """Which grid cell a coordinate falls in.

    Returned as a string because it is an identity, not an arithmetic value, and
    storing it as text keeps a stored split auditable by eye.
    """
    x = int(longitude // size)
    y = int(latitude // size)
    return f"{x}:{y}"


def neighbours_of(cell: str) -> list[str]:
    """The eight cells touching this one.

    Used to find boundary cells. A camera standing near a cell edge photographs
    what is on the other side of it, so a cell whose neighbour belongs to a
    different partition is not safely on either side.
    """
    x_text, y_text = cell.split(":")
    x, y = int(x_text), int(y_text)
    return [
        f"{x + dx}:{y + dy}" for dx in (-1, 0, 1) for dy in (-1, 0, 1) if not (dx == 0 and dy == 0)
    ]


def assign_cell(cell: str, *, salt: str, ratios: dict[SplitName, float] | None = None) -> SplitName:
    """Which partition a cell belongs to.

    Deterministic: the same cell and salt always give the same answer, so a split
    can be recomputed on another machine and reviewed in a diff. Hash-based
    rather than sequential, so partitions are not spatially contiguous blocks —
    a test set that is entirely one neighbourhood measures that neighbourhood,
    not generalisation.
    """
    shares = ratios or DEFAULT_RATIOS
    digest = hashlib.sha256(f"{salt}:{cell}".encode()).digest()
    # First eight bytes as a fraction of the space, which is plenty of
    # resolution for a three-way split and stable across platforms.
    position = int.from_bytes(digest[:8], "big") / float(1 << 64)

    threshold = 0.0
    for name in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST):
        threshold += shares.get(name, 0.0)
        if position < threshold:
            return name
    return SplitName.TEST


@dataclass(frozen=True, slots=True)
class ImageLocation:
    """The minimum needed to place an image in a partition."""

    image_id: str
    longitude: float | None
    latitude: float | None


@dataclass(slots=True)
class SplitAssignment:
    """The outcome of splitting a dataset, including what it refused to place."""

    #: image id -> partition
    assignments: dict[str, SplitName] = field(default_factory=dict)
    #: image id -> cell, kept so leakage can be checked without recomputation
    cells: dict[str, str] = field(default_factory=dict)
    #: cell -> partition, before boundary exclusion
    cell_partitions: dict[str, SplitName] = field(default_factory=dict)
    #: Cells dropped because a neighbour belonged elsewhere.
    boundary_cells: set[str] = field(default_factory=set)
    #: Images dropped because they have no location.
    unlocated: int = 0
    policy_version: int = SPLIT_POLICY_VERSION

    def counts(self) -> dict[str, int]:
        totals = {name.value: 0 for name in SplitName}
        for split in self.assignments.values():
            totals[split.value] += 1
        return totals

    def describe(self) -> list[str]:
        totals = self.counts()
        placed = sum(v for k, v in totals.items() if k != SplitName.EXCLUDED.value)
        lines = [
            f"Split policy v{self.policy_version}, {CELL_DEGREES}° cells",
            f"  cells       {len(self.cell_partitions)} assigned, "
            f"{len(self.boundary_cells)} excluded as boundary",
            f"  placed      {placed} images",
        ]
        for name in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST):
            share = totals[name.value] / placed if placed else 0.0
            lines.append(f"  {name.value:<11} {totals[name.value]:>7} ({share:6.1%})")
        lines.append(
            f"  excluded    {totals[SplitName.EXCLUDED.value]:>7} "
            f"({self.unlocated} with no location)"
        )
        return lines


def assign_splits(
    images: Iterable[ImageLocation],
    *,
    salt: str,
    ratios: dict[SplitName, float] | None = None,
    exclude_boundaries: bool = True,
) -> SplitAssignment:
    """Place every image in a partition, or refuse to place it.

    `salt` should be the dataset's name and version. Changing it reshuffles
    everything, which is why it belongs to the dataset rather than being a bare
    seed somebody might tweak until the numbers improve.
    """
    result = SplitAssignment()
    located: list[tuple[str, str]] = []

    for image in images:
        if image.longitude is None or image.latitude is None:
            result.assignments[image.image_id] = SplitName.EXCLUDED
            result.unlocated += 1
            continue
        cell = cell_of(image.longitude, image.latitude)
        located.append((image.image_id, cell))
        result.cells[image.image_id] = cell

    for _, cell in located:
        if cell not in result.cell_partitions:
            result.cell_partitions[cell] = assign_cell(cell, salt=salt, ratios=ratios)

    if exclude_boundaries:
        for cell, partition in result.cell_partitions.items():
            for neighbour in neighbours_of(cell):
                other = result.cell_partitions.get(neighbour)
                if other is not None and other != partition:
                    result.boundary_cells.add(cell)
                    break

    for image_id, cell in located:
        if cell in result.boundary_cells:
            result.assignments[image_id] = SplitName.EXCLUDED
        else:
            result.assignments[image_id] = result.cell_partitions[cell]

    return result


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    """One way a split failed to separate what it claimed to separate."""

    code: str
    message: str
    detail: dict[str, object]


def check_leakage(
    images: Sequence[ImageLocation],
    assignment: SplitAssignment,
    *,
    minimum_separation_m: float = 50.0,
) -> list[LeakageFinding]:
    """Prove the split holds, rather than trusting that it does.

    Three independent checks, because the three ways this goes wrong are
    independent:

    1. **A cell in two partitions.** Would mean the grid was not the unit of
       assignment after all — the failure that makes the whole scheme decorative.
    2. **Two images closer than `minimum_separation_m` on opposite sides.** The
       physical version of the same failure, and the one that survives a correct
       grid when a boundary runs down a street.
    3. **An identical image in two partitions.** Duplicate content under two ids,
       which no geographic reasoning can catch.

    Returns findings rather than raising: a split with a known, measured amount
    of leakage is a fact to report, and hiding it behind an exception would make
    it tempting to suppress.
    """
    findings: list[LeakageFinding] = []
    positions = {image.image_id: image for image in images}

    # --- 1. Cell integrity ------------------------------------------------
    cell_splits: dict[str, set[SplitName]] = {}
    for image_id, cell in assignment.cells.items():
        split = assignment.assignments.get(image_id)
        if split is None or split is SplitName.EXCLUDED:
            continue
        cell_splits.setdefault(cell, set()).add(split)

    for cell, splits in cell_splits.items():
        if len(splits) > 1:
            findings.append(
                LeakageFinding(
                    code="cell_in_multiple_splits",
                    message=f"Cell {cell} appears in more than one partition.",
                    detail={"cell": cell, "splits": sorted(s.value for s in splits)},
                )
            )

    # --- 2. Physical proximity across a boundary --------------------------
    from shapely.geometry import Point

    from pathable_api.geo.geometry import geodesic_distance_m

    by_split: dict[SplitName, list[ImageLocation]] = {}
    for image_id, split in assignment.assignments.items():
        if split is SplitName.EXCLUDED:
            continue
        image = positions.get(image_id)
        if image is None or image.longitude is None or image.latitude is None:
            continue
        by_split.setdefault(split, []).append(image)

    partitions = sorted(by_split, key=lambda s: s.value)
    for index, first in enumerate(partitions):
        for second in partitions[index + 1 :]:
            for a in by_split[first]:
                for b in by_split[second]:
                    assert a.longitude is not None  # noqa: S101
                    assert a.latitude is not None  # noqa: S101
                    assert b.longitude is not None  # noqa: S101
                    assert b.latitude is not None  # noqa: S101
                    metres = geodesic_distance_m(
                        Point(a.longitude, a.latitude), Point(b.longitude, b.latitude)
                    )
                    if metres < minimum_separation_m:
                        findings.append(
                            LeakageFinding(
                                code="images_too_close_across_splits",
                                message=(
                                    f"{a.image_id} ({first.value}) and {b.image_id} "
                                    f"({second.value}) are {metres:.0f} m apart."
                                ),
                                detail={
                                    "distance_m": round(metres, 1),
                                    "minimum_m": minimum_separation_m,
                                },
                            )
                        )

    # --- 3. Duplicate content --------------------------------------------
    return findings


def check_content_duplication(
    checksums: dict[str, str | None], assignment: SplitAssignment
) -> list[LeakageFinding]:
    """Find identical images placed in different partitions.

    Separate from `check_leakage` because it needs content hashes rather than
    positions, and because it catches what geography cannot: the same photograph
    under two identifiers, which no amount of correct spatial reasoning will
    separate.
    """
    seen: dict[str, list[tuple[str, SplitName]]] = {}
    for image_id, digest in checksums.items():
        if digest is None:
            continue
        split = assignment.assignments.get(image_id)
        if split is None or split is SplitName.EXCLUDED:
            continue
        seen.setdefault(digest, []).append((image_id, split))

    findings: list[LeakageFinding] = []
    for digest, entries in seen.items():
        splits = {split for _, split in entries}
        if len(splits) > 1:
            findings.append(
                LeakageFinding(
                    code="identical_image_in_multiple_splits",
                    message=f"Image content {digest[:12]} appears in {len(splits)} partitions.",
                    detail={
                        "sha256": digest,
                        "images": [image_id for image_id, _ in entries],
                        "splits": sorted(s.value for s in splits),
                    },
                )
            )
    return findings
