"""Activation and rollback, gated on evidence that is recorded and re-checked.

A candidate becomes the live network in three separate steps, and only the last
one touches what people route on:

1. **Evaluate.** Route a fixed journey corpus under every profile on the sealed
   candidate and on the dataset that is live now, and store both sets of
   outcomes and every difference, against both datasets' content checksums.
   This is the expensive part; it runs before, and outside, the switch.
2. **Accept**, only when there is something to accept: differences, or no live
   dataset to compare against. A person records why, in a sentence. Identical
   routes need no acceptance, and nothing bypasses one without a reason.
3. **Activate.** One short transaction, serialised per region: re-read the
   candidate, check that the stored evaluation still describes *this* content,
   this corpus and *today's* live dataset, then retire the incumbent, activate
   the candidate and write the event. No routing, hashing or enrichment inside.

**Rollback** reactivates a retired version exactly as it was — it does not
rebuild it. Its content is re-hashed first, outside the switch, and must match
the checksum it was sealed with; the switch then re-checks the stored value and
records the rollback with its reason.

The event log answers, later, "why is this dataset live, and what did we know
when it went live?" — including why it went live although routes changed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select

from pathable_api import __version__
from pathable_api.geo.content_checksum import (
    CONTENT_CHECKSUM_VERSION,
    ContentChecksum,
    compute_content_checksum,
)
from pathable_api.geo.datasets import DatasetLifecycleError, get_active_dataset
from pathable_api.geo.enums import DatasetStatus
from pathable_api.geo.fixtures import NODES as SYNTHETIC_NODES
from pathable_api.geo.fixtures import SYNTHETIC_REGION_SLUG
from pathable_api.geo.lifecycle import lock_dataset, seal_candidate
from pathable_api.geo.models import (
    REASON_MIN_CHARACTERS,
    DatasetActivationEvent,
    DatasetVersion,
    PilotRegion,
    RouteRegressionAcceptance,
    RouteRegressionRun,
)
from pathable_api.geo.regions import WATERLOO_SLUG
from pathable_api.routing.engine import (
    NoRouteFoundError,
    PointOffNetworkError,
    RequestTooLargeError,
    RoutingError,
    compute_route,
)
from pathable_api.routing.evaluation import RouteCase
from pathable_api.routing.graph import load_graph
from pathable_api.routing.profiles import (
    ROUTING_POLICY_VERSION,
    SELECTABLE_PROFILE_KEYS,
    STANDARD_PROFILE_KEY,
    get_profile,
)
from pathable_api.routing.waterloo_cases import WATERLOO_CASES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from pathable_api.routing.graph import RoutableGraph

IDENTICAL: Final = "identical"
DIFFERENCES: Final = "differences"
NO_BASELINE: Final = "no_baseline"

#: Every profile a person can choose, and the baseline they are compared with.
REGRESSION_PROFILES: Final[tuple[str, ...]] = (STANDARD_PROFILE_KEY, *SELECTABLE_PROFILE_KEYS)

#: The route fields compared between baseline and candidate. Timings and search
#: effort are left out: they describe the machine, not the route.
COMPARED_FIELDS: Final = (
    "routed",
    "failure_kind",
    "distance_m",
    "effective_distance_m",
    "duration_seconds",
    "segments",
    "path",
)


class ActivationRefusedError(DatasetLifecycleError):
    """The evidence an activation or rollback needs is missing or out of date."""


@dataclass(frozen=True, slots=True)
class Corpus:
    name: str
    cases: tuple[RouteCase, ...]


#: The synthetic fixture's own journeys, so its lifecycle is exercised the same
#: way a real region's is. Not Waterloo data.
SYNTHETIC_CASES: Final = (
    RouteCase(
        key="fixture-stairs-or-ramp",
        description="Across the fixture's stairway, or round it by the ramp",
        origin=SYNTHETIC_NODES["A"],
        destination=SYNTHETIC_NODES["D"],
    ),
    RouteCase(
        key="fixture-gravel-to-crossing",
        description="From the gravel path to the signalised crossing",
        origin=SYNTHETIC_NODES["G"],
        destination=SYNTHETIC_NODES["E"],
    ),
    RouteCase(
        key="fixture-one-way-passage",
        description="Through the one-way passage",
        origin=SYNTHETIC_NODES["H"],
        destination=SYNTHETIC_NODES["D"],
    ),
    RouteCase(
        key="fixture-untagged-geometry",
        description="Along geometry nobody has tagged",
        origin=SYNTHETIC_NODES["U"],
        destination=SYNTHETIC_NODES["F"],
    ),
)

CORPORA: Final[dict[str, Corpus]] = {
    WATERLOO_SLUG: Corpus(name="waterloo-journeys-v1", cases=WATERLOO_CASES),
    SYNTHETIC_REGION_SLUG: Corpus(name="synthetic-fixture-journeys-v1", cases=SYNTHETIC_CASES),
}


def corpus_for(region_slug: str) -> Corpus:
    corpus = CORPORA.get(region_slug)
    if corpus is None:
        msg = (
            f"Region {region_slug!r} has no route-regression corpus, so no candidate for it "
            "can be judged or activated. Add one to `CORPORA` before its first dataset."
        )
        raise ActivationRefusedError(msg)
    return corpus


def corpus_fingerprint(corpus: Corpus, profiles: tuple[str, ...] = REGRESSION_PROFILES) -> str:
    """The journeys, the profiles and the routing policy, as one hash.

    A run judged under one of these says nothing about another, so activation
    refuses a run whose fingerprint is not today's.
    """
    body = {
        "corpus": corpus.name,
        "cases": [[case.key, list(case.origin), list(case.destination)] for case in corpus.cases],
        "profiles": list(profiles),
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "compared_fields": list(COMPARED_FIELDS),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


def route_outcome(graph: RoutableGraph, case: RouteCase, profile_key: str) -> dict[str, Any]:
    """What one journey produced, reduced to the fields that define the route.

    ``path`` hashes the ordered segment identities and the travelled
    coordinates, so two routes of equal length along different streets differ,
    and so does the same street walked the other way.
    """
    profile = get_profile(profile_key)
    try:
        route = compute_route(
            graph, origin=case.origin, destination=case.destination, profile=profile
        )
    except (NoRouteFoundError, PointOffNetworkError, RequestTooLargeError, RoutingError) as error:
        return {
            "routed": False,
            "failure_kind": type(error).__name__,
            "distance_m": None,
            "effective_distance_m": None,
            "duration_seconds": None,
            "segments": 0,
            "path": None,
        }
    path = hashlib.sha256(
        json.dumps(
            {
                "segments": [segment.edge_identity for segment in route.segments],
                "coordinates": [list(position) for position in route.coordinates],
            }
        ).encode("utf-8")
    ).hexdigest()
    return {
        "routed": True,
        "failure_kind": None,
        "distance_m": round(route.distance_m, 3),
        "effective_distance_m": round(route.effective_distance_m, 3),
        "duration_seconds": round(route.estimated_duration_seconds, 3),
        "segments": len(route.segments),
        "path": path,
    }


def _route_corpus(
    graph: RoutableGraph, corpus: Corpus, profiles: tuple[str, ...]
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (case.key, profile): route_outcome(graph, case, profile)
        for case in corpus.cases
        for profile in profiles
    }


def compare_outcomes(
    candidate: dict[tuple[str, str], dict[str, Any]],
    baseline: dict[tuple[str, str], dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every outcome, and every field on which the two datasets disagree."""
    results: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []
    for (case, profile), outcome in candidate.items():
        before = None if baseline is None else baseline.get((case, profile))
        results.append({"case": case, "profile": profile, "candidate": outcome, "baseline": before})
        if before is None:
            continue
        for field in COMPARED_FIELDS:
            if outcome.get(field) != before.get(field):
                differences.append(
                    {
                        "case": case,
                        "profile": profile,
                        "field": field,
                        "baseline": before.get(field),
                        "candidate": outcome.get(field),
                    }
                )
    return results, differences


async def evaluate_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, *, app_version: str
) -> RouteRegressionRun:
    """Route the corpus on a sealed candidate and on the live dataset, and store it.

    The graphs are loaded straight from the rows, one at a time, rather than
    through the serving cache: this must describe exactly what is stored, and
    two city graphs need not be resident at once.
    """
    candidate = await session.get(DatasetVersion, candidate_id)
    if candidate is None:
        msg = f"Dataset {candidate_id} does not exist."
        raise ActivationRefusedError(msg)
    if candidate.status != DatasetStatus.VALIDATED or candidate.content_checksum is None:
        msg = (
            f"Dataset {candidate.id} is {candidate.status}; only a sealed (validated) candidate "
            "can be evaluated for activation. Seal it first."
        )
        raise ActivationRefusedError(msg)

    region = await session.get(PilotRegion, candidate.pilot_region_id)
    assert region is not None  # noqa: S101 - enforced by the foreign key
    corpus = corpus_for(region.slug)
    baseline = await get_active_dataset(session, region.id)
    if baseline is not None and baseline.content_checksum is None:
        msg = (
            f"The live dataset {baseline.id} predates content checksums. Record one from its "
            "rows first (`pathable datasets checksum --record`), so the comparison names the "
            "content it compared against."
        )
        raise ActivationRefusedError(msg)

    started_at = _utcnow()
    started = time.perf_counter()

    baseline_outcomes: dict[tuple[str, str], dict[str, Any]] | None = None
    if baseline is not None:
        baseline_graph = await load_graph(session, baseline, region.slug)
        baseline_outcomes = _route_corpus(baseline_graph, corpus, REGRESSION_PROFILES)
        del baseline_graph
    candidate_graph = await load_graph(session, candidate, region.slug)
    candidate_outcomes = _route_corpus(candidate_graph, corpus, REGRESSION_PROFILES)
    del candidate_graph

    results, differences = compare_outcomes(candidate_outcomes, baseline_outcomes)
    if baseline is None:
        outcome = NO_BASELINE
    elif differences:
        outcome = DIFFERENCES
    else:
        outcome = IDENTICAL

    run = RouteRegressionRun(
        id=uuid.uuid4(),
        pilot_region_id=region.id,
        candidate_dataset_id=candidate.id,
        candidate_content_checksum=candidate.content_checksum,
        baseline_dataset_id=None if baseline is None else baseline.id,
        baseline_content_checksum=None if baseline is None else baseline.content_checksum,
        corpus_key=corpus.name,
        corpus_fingerprint=corpus_fingerprint(corpus),
        profiles=list(REGRESSION_PROFILES),
        routing_policy_version=ROUTING_POLICY_VERSION,
        app_version=app_version,
        outcome=outcome,
        comparison_count=len(results),
        difference_count=len(differences),
        results=results,
        differences=differences,
        started_at=started_at,
        completed_at=_utcnow(),
        duration_seconds=round(time.perf_counter() - started, 3),
    )
    session.add(run)
    await session.flush()
    return run


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


def _clean_reason(reason: str | None) -> str:
    text = (reason or "").strip()
    if len(text) < REASON_MIN_CHARACTERS:
        msg = (
            f"A reason is required, in at least {REASON_MIN_CHARACTERS} characters: it is "
            "what somebody will read later to learn why this happened."
        )
        raise ActivationRefusedError(msg)
    return text


async def accept_regression(
    session: AsyncSession, run_id: uuid.UUID, *, reason: str
) -> RouteRegressionAcceptance:
    """Record that a run's differences, or its lack of a baseline, are intended."""
    text = _clean_reason(reason)
    run = await session.get(RouteRegressionRun, run_id)
    if run is None:
        msg = f"Route regression run {run_id} does not exist."
        raise ActivationRefusedError(msg)
    if run.outcome == IDENTICAL:
        msg = "That run found identical routes; there is nothing to accept."
        raise ActivationRefusedError(msg)
    existing = await _acceptance_for(session, run.id)
    if existing is not None:
        msg = f"That run was already accepted at {existing.accepted_at:%Y-%m-%d %H:%M:%S}Z."
        raise ActivationRefusedError(msg)
    acceptance = RouteRegressionAcceptance(
        id=uuid.uuid4(), regression_run_id=run.id, reason=text, accepted_at=_utcnow()
    )
    session.add(acceptance)
    await session.flush()
    return acceptance


async def _acceptance_for(
    session: AsyncSession, run_id: uuid.UUID
) -> RouteRegressionAcceptance | None:
    return (
        await session.execute(
            select(RouteRegressionAcceptance).where(
                RouteRegressionAcceptance.regression_run_id == run_id
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Switch:
    event: DatasetActivationEvent
    previous_id: uuid.UUID | None
    #: Wall time of the switch itself, from the region lock to the event row.
    seconds: float


async def _lock_region(session: AsyncSession, region_id: uuid.UUID) -> PilotRegion:
    """Serialise lifecycle changes per region: two switches cannot interleave."""
    return (
        await session.execute(
            select(PilotRegion)
            .where(PilotRegion.id == region_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _lock_active(session: AsyncSession, region_id: uuid.UUID) -> DatasetVersion | None:
    return (
        await session.execute(
            select(DatasetVersion)
            .where(
                DatasetVersion.pilot_region_id == region_id,
                DatasetVersion.status == DatasetStatus.ACTIVE,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _latest_run(
    session: AsyncSession, candidate: DatasetVersion
) -> RouteRegressionRun | None:
    return (
        await session.execute(
            select(RouteRegressionRun)
            .where(
                RouteRegressionRun.candidate_dataset_id == candidate.id,
                RouteRegressionRun.candidate_content_checksum == candidate.content_checksum,
            )
            .order_by(RouteRegressionRun.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def activate_candidate(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    regression_run_id: uuid.UUID | None = None,
) -> Switch:
    """Make a sealed, judged candidate the live network for its region.

    Runs in the caller's transaction, which should contain nothing else; the
    caller commits. Every check reads stored values — nothing is recomputed here.
    """
    started = time.perf_counter()
    probe = await session.get(DatasetVersion, candidate_id)
    if probe is None:
        msg = f"Dataset {candidate_id} does not exist."
        raise ActivationRefusedError(msg)
    region = await _lock_region(session, probe.pilot_region_id)
    candidate = await lock_dataset(session, candidate_id)

    if candidate.status != DatasetStatus.VALIDATED:
        msg = (
            f"Dataset {candidate.id} is {candidate.status}; only a sealed candidate can be "
            "activated. A retired dataset comes back through rollback."
        )
        raise ActivationRefusedError(msg)
    if candidate.content_checksum is None or candidate.content_checksum_version is None:
        msg = f"Dataset {candidate.id} has no content checksum."
        raise ActivationRefusedError(msg)
    if candidate.validated_content_checksum != candidate.content_checksum:
        msg = f"Dataset {candidate.id} was validated on different content than it now holds."
        raise ActivationRefusedError(msg)

    if regression_run_id is not None:
        run = await session.get(RouteRegressionRun, regression_run_id)
        if run is None or run.candidate_dataset_id != candidate.id:
            msg = f"Run {regression_run_id} is not a regression run for dataset {candidate.id}."
            raise ActivationRefusedError(msg)
    else:
        run = await _latest_run(session, candidate)
        if run is None:
            msg = (
                f"Dataset {candidate.id} has no route regression for its current content. "
                "Run `pathable datasets evaluate` first."
            )
            raise ActivationRefusedError(msg)
    if run.candidate_content_checksum != candidate.content_checksum:
        msg = "That regression run judged different content from what this dataset holds."
        raise ActivationRefusedError(msg)
    if run.corpus_fingerprint != corpus_fingerprint(corpus_for(region.slug)):
        msg = (
            "The corpus, the profiles or the routing policy changed since that run. "
            "Evaluate again under the current ones."
        )
        raise ActivationRefusedError(msg)

    active = await _lock_active(session, region.id)
    live = (None, None) if active is None else (active.id, active.content_checksum)
    if (run.baseline_dataset_id, run.baseline_content_checksum) != live:
        msg = (
            "The live dataset changed after that run compared against it. Evaluate again "
            "against the network that is live now."
        )
        raise ActivationRefusedError(msg)

    acceptance = None
    if run.outcome != IDENTICAL:
        acceptance = await _acceptance_for(session, run.id)
        if acceptance is None:
            what = (
                "there is no live dataset to compare against"
                if run.outcome == NO_BASELINE
                else f"routes changed in {run.difference_count} places"
            )
            msg = (
                f"Review required: {what}. Accept run {run.id} with a reason "
                "(`pathable datasets accept`) if that is intended."
            )
            raise ActivationRefusedError(msg)

    now = _utcnow()
    if active is not None:
        # Retire before activating: the partial unique index allows one active
        # row per region at every statement boundary, not just at commit.
        active.status = DatasetStatus.RETIRED
        active.retired_at = now
        await session.flush()
    candidate.status = DatasetStatus.ACTIVE
    candidate.activated_at = now
    candidate.retired_at = None
    event = DatasetActivationEvent(
        id=uuid.uuid4(),
        pilot_region_id=region.id,
        action="activate",
        from_dataset_id=None if active is None else active.id,
        to_dataset_id=candidate.id,
        to_content_checksum=candidate.content_checksum,
        regression_run_id=run.id,
        acceptance_id=None if acceptance is None else acceptance.id,
        reason=None,
        occurred_at=now,
    )
    session.add(event)
    await session.flush()
    return Switch(
        event=event,
        previous_id=None if active is None else active.id,
        seconds=time.perf_counter() - started,
    )


# ---------------------------------------------------------------------------
# Roll back
# ---------------------------------------------------------------------------


async def rollback_target(
    session: AsyncSession, region_id: uuid.UUID, target_id: uuid.UUID | None
) -> DatasetVersion:
    """The dataset to reactivate: the one named, or the one live before the current one."""
    if target_id is not None:
        target = await session.get(DatasetVersion, target_id)
        if target is None:
            msg = f"Dataset {target_id} does not exist."
            raise ActivationRefusedError(msg)
        if target.pilot_region_id != region_id:
            msg = f"Dataset {target.id} belongs to another region."
            raise ActivationRefusedError(msg)
        return target

    active = await get_active_dataset(session, region_id)
    if active is None:
        msg = "The region has no live dataset to roll back from."
        raise ActivationRefusedError(msg)
    arrival = (
        await session.execute(
            select(DatasetActivationEvent)
            .where(
                DatasetActivationEvent.pilot_region_id == region_id,
                DatasetActivationEvent.to_dataset_id == active.id,
            )
            .order_by(DatasetActivationEvent.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if arrival is None or arrival.from_dataset_id is None:
        msg = (
            "No recorded activation says what was live before the current dataset. "
            "Name the dataset to roll back to."
        )
        raise ActivationRefusedError(msg)
    target = await session.get(DatasetVersion, arrival.from_dataset_id)
    assert target is not None  # noqa: S101 - enforced by the foreign key
    return target


async def verify_rollback_target(session: AsyncSession, target: DatasetVersion) -> ContentChecksum:
    """Re-hash a rollback target from its rows; refuse it unless it matches.

    Outside the switch on purpose: hashing a city takes seconds, and the switch
    must not hold the region while it does.
    """
    if target.status != DatasetStatus.RETIRED or target.activated_at is None:
        msg = (
            f"Dataset {target.id} is {target.status}"
            + ("" if target.activated_at else " and was never live")
            + "; only a retired dataset that was once live can be rolled back to."
        )
        raise ActivationRefusedError(msg)
    if target.content_checksum is None:
        msg = (
            f"Dataset {target.id} predates content checksums. Record one from its rows "
            "(`pathable datasets checksum --record`) before rolling back to it."
        )
        raise ActivationRefusedError(msg)
    if target.content_checksum_version != CONTENT_CHECKSUM_VERSION:
        msg = (
            f"Dataset {target.id} was hashed under content contract "
            f"v{target.content_checksum_version}, not v{CONTENT_CHECKSUM_VERSION}."
        )
        raise ActivationRefusedError(msg)
    computed = await compute_content_checksum(session, target.id)
    if computed.value != target.content_checksum:
        msg = (
            f"Dataset {target.id} no longer matches the content it was sealed with "
            f"(rows hash to {computed.value[:12]}, recorded {target.content_checksum[:12]}). "
            "It cannot be trusted as a rollback target."
        )
        raise ActivationRefusedError(msg)
    return computed


async def rollback(
    session: AsyncSession,
    *,
    region_id: uuid.UUID,
    target_id: uuid.UUID,
    verified_checksum: str,
    reason: str,
) -> Switch:
    """Reactivate a retired dataset, as it was, in one short transaction.

    ``verified_checksum`` is what :func:`verify_rollback_target` recomputed; the
    switch re-reads the stored value and refuses if they differ.
    """
    text = _clean_reason(reason)
    started = time.perf_counter()
    region = await _lock_region(session, region_id)
    target = await lock_dataset(session, target_id)
    if target.pilot_region_id != region.id:
        msg = f"Dataset {target.id} belongs to another region."
        raise ActivationRefusedError(msg)
    if target.status != DatasetStatus.RETIRED or target.activated_at is None:
        msg = f"Dataset {target.id} is {target.status}; it cannot be rolled back to."
        raise ActivationRefusedError(msg)
    if target.content_checksum != verified_checksum:
        msg = f"Dataset {target.id} changed after it was verified."
        raise ActivationRefusedError(msg)

    active = await _lock_active(session, region.id)
    if active is None:
        msg = "The region has no live dataset to roll back from."
        raise ActivationRefusedError(msg)

    now = _utcnow()
    active.status = DatasetStatus.RETIRED
    active.retired_at = now
    await session.flush()
    target.status = DatasetStatus.ACTIVE
    target.activated_at = now
    target.retired_at = None
    event = DatasetActivationEvent(
        id=uuid.uuid4(),
        pilot_region_id=region.id,
        action="rollback",
        from_dataset_id=active.id,
        to_dataset_id=target.id,
        to_content_checksum=verified_checksum,
        regression_run_id=None,
        acceptance_id=None,
        reason=text,
        occurred_at=now,
    )
    session.add(event)
    await session.flush()
    return Switch(event=event, previous_id=active.id, seconds=time.perf_counter() - started)


async def promote(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    *,
    acceptance_reason: str | None = None,
) -> Switch:
    """Seal, evaluate and activate a candidate, in that order, with the same gates.

    A convenience for test fixtures and bootstrap scripts, not a way around
    anything: each step is the one an operator would run, and a run that needs
    acceptance is accepted only with the reason given — without one, promotion
    stops where an operator would be stopped.
    """
    await seal_candidate(session, candidate_id)
    run = await evaluate_candidate(session, candidate_id, app_version=__version__)
    if run.outcome != IDENTICAL:
        if acceptance_reason is None:
            msg = (
                f"Review required for run {run.id} ({run.outcome}); promotion without an "
                "acceptance reason stops here."
            )
            raise ActivationRefusedError(msg)
        await accept_regression(session, run.id, reason=acceptance_reason)
    return await activate_candidate(session, candidate_id, regression_run_id=run.id)


async def activation_history(
    session: AsyncSession, region_id: uuid.UUID
) -> list[DatasetActivationEvent]:
    return list(
        (
            await session.execute(
                select(DatasetActivationEvent)
                .where(DatasetActivationEvent.pilot_region_id == region_id)
                .order_by(DatasetActivationEvent.occurred_at)
            )
        ).scalars()
    )
