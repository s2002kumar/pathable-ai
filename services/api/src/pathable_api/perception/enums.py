"""Vocabulary for the perception system.

Kept apart from `geo.enums` deliberately. Those describe what a map says; these
describe what a model predicted and how far we trust it. Merging them would make
it easy to write code that cannot tell the two apart, which is the one thing this
subsystem must never allow.
"""

from __future__ import annotations

from enum import StrEnum


class LabelClass(StrEnum):
    """What a labeller decided about one image.

    Four values, not two. A binary stairs/not-stairs vocabulary forces a labeller
    to guess on the hard cases, and those guesses become training noise that is
    indistinguishable from signal. Naming the difficulty keeps it out of the
    training set and available for review.
    """

    #: A flight of steps is present and identifiable.
    STAIRS = "stairs"
    #: No steps. Includes the deliberate negatives — ramps, kerbs, shadows,
    #: markings — which is the point of having them.
    NOT_STAIRS = "not_stairs"
    #: Steps may be present but a careful person cannot be sure: too distant,
    #: too occluded, or genuinely borderline. Excluded from training, kept for
    #: review, and counted in every report.
    AMBIGUOUS = "ambiguous"
    #: The image cannot be judged at all — blurred, dark, obstructed, corrupt.
    #: A property of the capture, not of the scene.
    UNUSABLE = "unusable"


class ReviewState(StrEnum):
    """How much scrutiny a label has had.

    Recorded per label because a single-pass label and one two people agreed on
    are different evidence, and an evaluation that mixes them silently overstates
    its own ground truth.
    """

    UNREVIEWED = "unreviewed"
    #: A second labeller agreed.
    CONFIRMED = "confirmed"
    #: A second labeller disagreed. Excluded from training until resolved.
    DISPUTED = "disputed"
    #: Reviewed and corrected; the current label is the corrected one.
    CORRECTED = "corrected"


class QualityFlag(StrEnum):
    """Why an image might be hard, recorded whether or not it was labelled.

    These exist so failure analysis can ask "does the model fail on night
    images?" without re-inspecting every failure by hand.
    """

    NIGHT = "night"
    LOW_LIGHT = "low_light"
    MOTION_BLUR = "motion_blur"
    OCCLUDED = "occluded"
    DISTANT = "distant"
    WEATHER = "weather"
    SNOW = "snow"
    INDOOR = "indoor"
    #: Faces or plates present and not yet obscured. Blocks use until cleared.
    CONTAINS_PEOPLE = "contains_people"


class SplitName(StrEnum):
    """Which geographic partition an image belongs to.

    A split is a property of *place*, not of the image, so two frames of the same
    staircase can never land on opposite sides of it.
    """

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    #: Deliberately withheld from every split — usually because its location is
    #: unknown, so it cannot be assigned to a geographic partition honestly.
    EXCLUDED = "excluded"


class ModelState(StrEnum):
    """Where a model version sits in its lifecycle.

    Exactly one model may be `ACTIVE` at a time. Promotion is explicit and
    reversible: retiring the active model returns the system to deterministic
    routing rather than to no routing.
    """

    #: Trained, not yet evaluated on the held-out test set.
    CANDIDATE = "candidate"
    #: Evaluated and calibrated, meets the promotion criteria, not yet serving.
    VALIDATED = "validated"
    #: Serving predictions that influence routing.
    ACTIVE = "active"
    #: Withdrawn. Kept, because rollback means re-activating a previous version.
    RETIRED = "retired"


class PredictionType(StrEnum):
    """What a stored prediction is about.

    Only one for now. It is an enum rather than a bare string so that the second
    one cannot be added without deciding what it means.
    """

    STAIRS = "stairs"
