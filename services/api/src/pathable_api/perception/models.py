"""Storage for training data, models and predictions.

Three rules shape every table here.

**A prediction is never a map fact.** Predictions live in their own table, keyed
to the segment they describe rather than written onto it. No column in `geo` is
ever updated by this subsystem. A route can therefore always answer "did
OpenStreetMap say this, or did a model?", which is the distinction the whole
product rests on.

**Images stay out of the database and out of Git.** What is stored is a manifest:
where an image came from, under what licence, what was decided about it, and a
checksum. The bytes live wherever they were licensed from.

**A split is a property of place.** Geographic partitions are assigned to cells,
not to images, so two frames of the same staircase cannot land on opposite sides
of a train/test boundary.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pathable_api.db.base import Base
from pathable_api.geo.models import SRID, TimestampMixin, _enum_check
from pathable_api.perception.enums import (
    LabelClass,
    ModelState,
    PredictionType,
    ReviewState,
    SplitName,
)


class ImageDataset(TimestampMixin, Base):
    """One versioned collection of images, with the licence that permits its use.

    Versioned for the same reason network datasets are: an evaluation is only
    meaningful against a stated corpus, and a corpus that changes underneath a
    published number makes the number a fiction.
    """

    __tablename__ = "image_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    #: Human name, e.g. "exonet". Stable across versions.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Monotonic per name.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Where it came from, and the identifier that lets somebody else fetch it.
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    source_doi: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)

    #: The licence, recorded as its identifier rather than as prose so a query
    #: can find every image under a share-alike obligation.
    licence: Mapped[str] = mapped_column(String(64), nullable=False)
    licence_url: Mapped[str | None] = mapped_column(Text)
    #: The credit that must appear wherever this data or its consequences show.
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    #: True when the licence permits commercial use. Recorded rather than
    #: inferred, because inferring it from a licence name is how a
    #: non-commercial dataset ends up in a commercial model.
    commercial_use_permitted: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: True when the licence imposes share-alike on derived works.
    share_alike: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: How the images were originally produced — "self-captured", "web", mixed.
    #: A dataset whose provenance cannot be stated is not usable.
    provenance_note: Mapped[str] = mapped_column(Text, nullable=False)

    acquired_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Checksum over the manifest, so "is this the same corpus?" is answerable.
    manifest_checksum: Mapped[str | None] = mapped_column(String(64))

    images: Mapped[list[DatasetImage]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_image_dataset_version"),
        CheckConstraint("version > 0", name="image_dataset_version_positive"),
    )


class DatasetImage(TimestampMixin, Base):
    """One image's manifest entry. The bytes are elsewhere."""

    __tablename__ = "dataset_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("image_datasets.id", ondelete="CASCADE"), nullable=False
    )

    #: The identifier used by the source, so a record can be traced upstream.
    source_image_id: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Path relative to the dataset root. Never absolute — the root moves.
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    #: Content hash. Two datasets containing the same image are detectable, and
    #: an image that changed under a stored label is detectable.
    sha256: Mapped[str | None] = mapped_column(String(64))

    #: When the photograph was taken, not when it was downloaded. Null when the
    #: source does not record it, which is common and worth knowing.
    captured_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    #: Where it was taken. Null is normal: most public datasets do not
    #: geolocate, and such an image cannot join a geographic split honestly.
    location: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=SRID, spatial_index=False))

    #: Which geographic partition this image belongs to, resolved from its cell.
    split: Mapped[SplitName] = mapped_column(String(16), nullable=False, default=SplitName.EXCLUDED)
    #: The cell that decided the split. Stored so leakage can be checked without
    #: recomputing the assignment.
    split_cell: Mapped[str | None] = mapped_column(String(32))

    #: Capture conditions worth knowing about, whatever the label says.
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    dataset: Mapped[ImageDataset] = relationship(back_populates="images")
    labels: Mapped[list[ImageLabel]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("dataset_id", "source_image_id", name="uq_dataset_image_identity"),
        _enum_check("split", SplitName, "image_split"),
        Index("ix_dataset_images_dataset", "dataset_id"),
        Index("ix_dataset_images_split", "dataset_id", "split"),
        Index("ix_dataset_images_location", "location", postgresql_using="gist"),
    )


class ImageLabel(TimestampMixin, Base):
    """What somebody decided about one image, and how sure that decision is."""

    __tablename__ = "image_labels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_images.id", ondelete="CASCADE"), nullable=False
    )

    label: Mapped[LabelClass] = mapped_column(String(16), nullable=False)
    review_state: Mapped[ReviewState] = mapped_column(
        String(16), nullable=False, default=ReviewState.UNREVIEWED
    )

    #: Who or what decided. A person, or the name of an import that carried the
    #: source's own labels through. Never blank.
    labelled_by: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Why, when the answer is not obvious. Required for AMBIGUOUS, because
    #: "unclear" without a reason cannot be reviewed.
    note: Mapped[str | None] = mapped_column(Text)

    #: Where the steps are, when the label is STAIRS and the source localised
    #: them. Normalised [x, y, w, h] in 0..1 so it survives resizing.
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)

    image: Mapped[DatasetImage] = relationship(back_populates="labels")

    __table_args__ = (
        _enum_check("label", LabelClass, "image_label_class"),
        _enum_check("review_state", ReviewState, "image_label_review"),
        Index("ix_image_labels_image", "image_id"),
    )


class ModelVersion(TimestampMixin, Base):
    """One trained model, everything needed to reproduce it, and its verdict."""

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[ModelState] = mapped_column(
        String(16), nullable=False, default=ModelState.CANDIDATE
    )

    prediction_type: Mapped[PredictionType] = mapped_column(String(16), nullable=False)

    # --- Reproducibility -------------------------------------------------
    #: The corpus it learned from. Without this an evaluation number is
    #: unattributable.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("image_datasets.id", ondelete="RESTRICT")
    )
    #: The commit the training code was at.
    code_sha: Mapped[str | None] = mapped_column(String(64))
    architecture: Mapped[str | None] = mapped_column(String(120))
    pretrained_weights: Mapped[str | None] = mapped_column(String(200))
    #: Hyperparameters, augmentations, seed, hardware, duration — everything
    #: needed to run it again, kept as a document because the shape of it
    #: changes faster than a schema should.
    training_run: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # --- What it is worth ------------------------------------------------
    #: Measured on the held-out geographic test set, once, at promotion time.
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Calibration fitted on validation, never on test.
    calibration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: What it gets wrong, by category. Recorded because a model whose failures
    #: are unexamined cannot be promoted responsibly.
    failure_analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    #: Where the weights are, and their hash. Weights stay out of Git.
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))

    promoted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why it was promoted or retired, in words a person can disagree with.
    promotion_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_version"),
        _enum_check("state", ModelState, "model_state"),
        _enum_check("prediction_type", PredictionType, "model_prediction_type"),
        CheckConstraint("version > 0", name="model_version_positive"),
        # At most one active model per prediction type, enforced by the database
        # rather than by whoever remembers to check. The same discipline the
        # dataset lifecycle already uses.
        Index(
            "uq_one_active_model_per_type",
            "prediction_type",
            unique=True,
            postgresql_where=(state == ModelState.ACTIVE),
        ),
    )


class SegmentPrediction(TimestampMixin, Base):
    """What a model believes about one segment.

    Deliberately its own table. Writing this onto `graph_edges` would make a
    prediction indistinguishable from a survey, and no amount of naming
    discipline survives a column that both can write to.
    """

    __tablename__ = "segment_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    prediction_type: Mapped[PredictionType] = mapped_column(String(16), nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )

    #: The segment this is about, by its stable source identity rather than by
    #: row id — so a prediction survives re-ingesting the network.
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_u: Mapped[str] = mapped_column(String(64), nullable=False)
    source_v: Mapped[str] = mapped_column(String(64), nullable=False)
    edge_key: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: What the model actually output, before calibration.
    raw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    #: What that probability means after calibration. This is the number the
    #: cost model may use; the raw one is kept so calibration can be re-fitted
    #: without re-running inference.
    calibrated_probability: Mapped[float] = mapped_column(Float, nullable=False)

    #: Which image produced it, and where that image came from — so a surprising
    #: prediction can be looked at rather than argued about.
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_images.id", ondelete="SET NULL")
    )
    image_captured_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    predicted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    model_version: Mapped[ModelVersion] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "model_version_id",
            "dataset_version_id",
            "source_u",
            "source_v",
            "edge_key",
            "prediction_type",
            name="uq_prediction_identity",
        ),
        _enum_check("prediction_type", PredictionType, "prediction_type"),
        CheckConstraint(
            "raw_probability >= 0 AND raw_probability <= 1", name="prediction_raw_probability"
        ),
        CheckConstraint(
            "calibrated_probability >= 0 AND calibrated_probability <= 1",
            name="prediction_calibrated_probability",
        ),
        Index(
            "ix_segment_predictions_lookup",
            "dataset_version_id",
            "prediction_type",
            "source_u",
            "source_v",
        ),
    )
