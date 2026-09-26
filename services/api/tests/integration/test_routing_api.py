"""The routing API, end to end against real PostGIS.

The synthetic fixture is loaded into a throwaway database and routed over
through the real HTTP stack, so these tests cover the parts that unit tests
cannot: the graph repository reading PostGIS, the dataset-version cache, the
response contract, and the failure paths a client will actually hit.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pathable_api.core.config import Settings
from pathable_api.core.event_loop import selector_loop_factory
from pathable_api.geo.elevation import HRDEM_ATTRIBUTION, ElevationSample
from pathable_api.geo.elevation_apply import apply_elevation
from pathable_api.geo.fixtures import NODES, SYNTHETIC_REGION_SLUG, load_synthetic_dataset
from pathable_api.geo.models import DatasetVersion
from pathable_api.main import create_app
from pathable_api.routing.activation import promote
from pathable_api.routing.graph import GraphRepository, RoutableGraph

pytestmark = pytest.mark.integration

COMPARE = "/api/v1/routes/compare"

A = {"longitude": NODES["A"][0], "latitude": NODES["A"][1]}
D = {"longitude": NODES["D"][0], "latitude": NODES["D"][1]}


@pytest_asyncio.fixture
async def seeded_database_url(
    migrated_database_url: str, db_session: AsyncSession
) -> AsyncIterator[str]:
    """A migrated database with the synthetic network active."""
    await load_synthetic_dataset(db_session)
    await db_session.commit()
    yield migrated_database_url


@pytest.fixture
def client(seeded_database_url: str) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=seeded_database_url,
        allowed_origins=("http://localhost:3000",),
        log_level="WARNING",
        log_format="console",
    )
    app: FastAPI = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def compare(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "region": SYNTHETIC_REGION_SLUG,
        "origin": A,
        "destination": D,
        "profile": "wheelchair",
    }
    payload.update(overrides)
    response = client.post(COMPARE, json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestProfileListing:
    def test_it_lists_the_selectable_profiles(self, client: TestClient) -> None:
        response = client.get("/api/v1/routes/profiles")

        assert response.status_code == 200
        keys = {profile["key"] for profile in response.json()["profiles"]}
        assert keys == {"wheelchair", "walker", "crutches", "stroller", "reduced_mobility"}

    def test_it_does_not_offer_the_baseline_as_a_mobility_choice(self, client: TestClient) -> None:
        response = client.get("/api/v1/routes/profiles")
        keys = {profile["key"] for profile in response.json()["profiles"]}

        assert "standard" not in keys

    def test_each_profile_states_its_hard_constraints(self, client: TestClient) -> None:
        profiles = {p["key"]: p for p in client.get("/api/v1/routes/profiles").json()["profiles"]}

        assert profiles["wheelchair"]["excludes_steps"] is True
        assert profiles["crutches"]["excludes_steps"] is False

        # A preset must not claim a generic threshold is a physical impossibility.
        # The wheelchair profile excludes known stairs — a real, visible
        # constraint — but its 8% gradient preference is guidance that makes a
        # steep segment expensive, not a limit that deletes it from the map.
        # Only a limit the user declared themselves becomes a hard exclusion.
        assert profiles["wheelchair"]["max_incline_percent"] is None


class TestCompare:
    def test_it_returns_both_routes(self, client: TestClient) -> None:
        body = compare(client)

        assert body["standard_route"] is not None
        assert body["accessible_route"] is not None

    def test_the_accessible_route_avoids_the_stairway(self, client: TestClient) -> None:
        body = compare(client)

        assert body["standard_route"]["stairway_count"] == 1
        assert body["accessible_route"]["stairway_count"] == 0

    def test_it_reports_the_extra_distance(self, client: TestClient) -> None:
        body = compare(client)

        assert body["extra_distance_m"] > 0
        assert body["extra_distance_fraction"] > 0

    def test_it_never_claims_a_model_was_used(self, client: TestClient) -> None:
        assert compare(client)["ml_predictions_used"] is False

    def test_it_returns_evidence_backed_explanations(self, client: TestClient) -> None:
        body = compare(client)
        codes = {item["code"] for item in body["explanations"]}

        assert "avoids_stairs" in codes
        for explanation in body["explanations"]:
            assert explanation["summary"].strip()
            assert explanation["evidence"]

    def test_it_warns_about_missing_accessibility_data(self, client: TestClient) -> None:
        body = compare(client)
        codes = {item["code"] for item in body["cautions"]}

        assert "missing_accessibility_data" in codes

    def test_segments_report_unknown_rather_than_false(self, client: TestClient) -> None:
        # The single most important thing on the wire: a client must not be able
        # to render "no steps" for a segment nobody has surveyed.
        body = compare(client)
        values = {segment["steps"] for segment in body["standard_route"]["segments"]}

        assert values <= {"yes", "no", "unknown"}
        # A boolean on the wire would mean the API had collapsed "nobody
        # recorded this" into "no", which is the failure this guards.
        assert all(isinstance(value, str) for value in values)

    def test_every_segment_shows_its_working(self, client: TestClient) -> None:
        body = compare(client)

        for segment in body["accessible_route"]["segments"]:
            assert segment["cost_components"]
            total = sum(c["effective_metres"] for c in segment["cost_components"])
            assert total == pytest.approx(segment["effective_metres"], abs=0.5)

    def test_the_polyline_starts_and_ends_where_the_route_does(self, client: TestClient) -> None:
        body = compare(client)
        route = body["accessible_route"]

        assert route["coordinates"][0] == pytest.approx(
            [route["origin"]["longitude"], route["origin"]["latitude"]]
        )
        assert route["coordinates"][-1] == pytest.approx(
            [route["destination"]["longitude"], route["destination"]["latitude"]]
        )

    def test_a_different_profile_can_produce_a_different_route(self, client: TestClient) -> None:
        wheelchair = compare(client, profile="wheelchair")["accessible_route"]
        reduced = compare(client, profile="reduced_mobility")["accessible_route"]

        assert wheelchair["profile"] == "wheelchair"
        assert reduced["profile"] == "reduced_mobility"

    def test_both_routes_are_timed_at_the_travellers_pace(self, client: TestClient) -> None:
        # Regression (D5): the shortest route's estimate used a standard walking
        # pace beside the accessible route's wheelchair pace, so the two times
        # on screen were not comparable.
        body = compare(client, profile="walker")

        assert body["standard_route"]["pace_profile"] == "walker"
        assert body["accessible_route"]["pace_profile"] == "walker"

    def test_a_custom_profile_is_timed_at_its_base_pace(self, client: TestClient) -> None:
        # Regression (D3), through the API: "custom" used to mean wheelchair pace.
        body = compare(
            client,
            profile="custom",
            custom={"base": "stroller", "max_incline_percent": 10},
        )

        assert body["accessible_route"]["pace_profile"] == "stroller"
        assert body["standard_route"]["pace_profile"] == "stroller"

    def test_every_explanation_names_what_it_rests_on(self, client: TestClient) -> None:
        body = compare(client)
        by_code = {item["code"]: item for item in body["explanations"]}

        allowed = {"recorded", "estimated", "mixed", "not_recorded", "profile_rule"}
        assert all(item["basis"] in allowed for item in body["explanations"])
        # Regression (D6): an absence of data must never carry a "recorded" label.
        assert by_code["avoids_unrecorded_kerbs"]["basis"] == "not_recorded"
        assert by_code["avoids_stairs"]["basis"] == "recorded"
        assert by_code["distance_difference"]["basis"] == "profile_rule"

    def test_the_detour_is_explained_by_every_constraint_not_stairs_alone(
        self, client: TestClient
    ) -> None:
        # Regression (D7): the synthetic detour avoids a stairway *and* an
        # unmarked crossing whose kerb nobody recorded; both must be stated.
        codes = [item["code"] for item in compare(client)["explanations"]]

        assert "avoids_stairs" in codes
        assert "avoids_unrecorded_kerbs" in codes
        assert "fewer_unmarked_crossings" in codes

    def test_the_shortest_route_marks_what_the_profile_rules_out(self, client: TestClient) -> None:
        body = compare(client)

        excluded = [
            segment
            for segment in body["standard_route"]["segments"]
            if segment["excluded_by_profile"] is not None
        ]
        assert [segment["excluded_by_profile"] for segment in excluded] == ["steps"]
        assert excluded[0]["steps"] == "yes"
        assert all(
            segment["excluded_by_profile"] is None
            for segment in body["accessible_route"]["segments"]
        )

    def test_every_route_carries_a_gradient_summary(self, client: TestClient) -> None:
        # No elevation in this dataset: every gradient is either recorded by a
        # mapper or unknown — and the summary must say which, not call it flat.
        route = compare(client)["accessible_route"]
        gradient = route["gradient"]

        assert gradient["estimated_fraction"] == 0
        assert gradient["recorded_fraction"] + gradient["unknown_fraction"] == pytest.approx(
            1.0, abs=1e-3
        )
        assert gradient["steepest_uphill"]["source"] == "osm_incline"
        assert gradient["steepest_uphill"]["percent"] == pytest.approx(4.0)


class TestProvenance:
    def test_every_response_names_the_dataset_it_came_from(self, client: TestClient) -> None:
        dataset = compare(client)["dataset"]

        assert dataset["region"] == SYNTHETIC_REGION_SLUG
        assert dataset["source_type"] == "synthetic"
        assert len(dataset["checksum"]) == 64
        assert dataset["acquired_at"]

    def test_synthetic_data_is_never_presented_as_a_survey(self, client: TestClient) -> None:
        attribution = compare(client)["dataset"]["attribution"]
        assert "not a survey" in attribution.lower()

    def test_a_dataset_with_no_elevation_owes_no_elevation_credit(self, client: TestClient) -> None:
        # Null, not an empty string and not the HRDEM line: a credit for a
        # model that produced nothing here would be as misleading as no credit
        # for one that did.
        assert compare(client)["dataset"]["elevation_attribution"] is None

    def test_hrdem_grades_carry_the_open_government_licence_credit(
        self, seeded_database_url: str
    ) -> None:
        # The Open Government Licence - Canada requires its statement on every
        # surface showing a derived grade. Before this test the API had no way
        # to say it, so the route panel could not either. The provider is a
        # stand-in so the test never touches NRCan's S3 bucket; what is under
        # test is that the stored source name reaches the response as the credit.
        #
        # Elevation is applied on its own loop, as the CLI does, rather than
        # from inside an async test: the TestClient below runs the app on a
        # second thread, and holding this test's loop while it does is a
        # deadlock on Windows.
        asyncio.run(_apply_fake_hrdem(seeded_database_url), loop_factory=selector_loop_factory())

        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=seeded_database_url,
            allowed_origins=("http://localhost:3000",),
            log_level="WARNING",
            log_format="console",
        )
        with TestClient(create_app(settings)) as test_client:
            body = compare(test_client)

        assert body["dataset"]["elevation_attribution"] == HRDEM_ATTRIBUTION
        assert "Open Government Licence" in body["dataset"]["elevation_attribution"]


async def _apply_fake_hrdem(database_url: str, provider: _LabelledAsHrdem | None = None) -> None:
    """Build an elevated candidate and put it live in place of the fixture.

    Elevation is applied only to a candidate — the live dataset is sealed —
    so this goes the way an operator would: a fresh build, enriched with the
    given terrain, then promoted through the regression gate with the reason
    recorded.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            candidate = await load_synthetic_dataset(session, activate=False)
            dataset = await session.get(DatasetVersion, candidate.dataset_id)
            assert dataset is not None
            await apply_elevation(session, dataset=dataset, provider=provider or _LabelledAsHrdem())
            await promote(
                session,
                candidate.dataset_id,
                acceptance_reason="A stand-in terrain replaces the tagged gradients in a test.",
            )
            await session.commit()
    finally:
        await engine.dispose()


class _LabelledAsHrdem:
    """A flat world that records itself under HRDEM's source name."""

    name = "nrcan-hrdem"
    dataset = "fake-hrdem"
    resolution_m: float | None = 1.0
    enabled = True
    attribution = HRDEM_ATTRIBUTION

    def elevation(self, _longitude: float, _latitude: float) -> float:
        return 300.0

    async def sample(self, points: Sequence[tuple[float, float]]) -> list[ElevationSample]:
        return [
            ElevationSample(
                longitude,
                latitude,
                self.elevation(longitude, latitude),
                self.name,
                self.dataset,
                self.resolution_m,
            )
            for longitude, latitude in points
        ]


class _RisingNorthward(_LabelledAsHrdem):
    """Ground that climbs 2% to the north, so segments off the east-west axis slope.

    Gentle on purpose: the only segment of the synthetic step-free route with no
    recorded incline (the signalised crossing, C -> E) gets an estimate of about
    1.6%, while the mapper's 4% on the ramp stays the steepest — the exact mix in
    which the interface once credited the recorded figure to the terrain model.
    """

    def elevation(self, _longitude: float, latitude: float) -> float:
        return 300.0 + 0.02 * (latitude - NODES["F"][1]) * 111_320.0


@pytest.fixture
def sloped_client(seeded_database_url: str) -> Iterator[TestClient]:
    # Applied on its own loop before the app starts, for the reason given in
    # test_hrdem_grades_carry_the_open_government_licence_credit.
    asyncio.run(
        _apply_fake_hrdem(seeded_database_url, _RisingNorthward()),
        loop_factory=selector_loop_factory(),
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=seeded_database_url,
        allowed_origins=("http://localhost:3000",),
        log_level="WARNING",
        log_format="console",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class TestEstimatedGradient:
    """Elevation-derived gradient, through PostGIS, the graph loader and the API."""

    def test_estimates_reach_the_response_beside_what_mappers_recorded(
        self, sloped_client: TestClient
    ) -> None:
        # Regression (D2): the estimate shaped route cost but had no field on the
        # wire, so no client could show a single estimated number.
        route = compare(sloped_client)["accessible_route"]
        crossing = next(
            segment for segment in route["segments"] if segment["incline_percent"] is None
        )

        assert crossing["derived_grade_percent"] == pytest.approx(1.6, abs=0.2)
        assert route["gradient_source"] == "mixed"
        assert 0 < route["gradient"]["estimated_fraction"] < 1

    def test_the_steepest_recorded_gradient_is_labelled_recorded_on_a_mixed_route(
        self, sloped_client: TestClient
    ) -> None:
        # Regression (D1): on a route mixing recorded and estimated gradients the
        # interface said the steepest one "comes from a terrain model" — but the
        # only figure it had was OSM's. The summary now says which it is.
        route = compare(sloped_client)["accessible_route"]
        steepest = route["gradient"]["steepest_uphill"]

        assert steepest["source"] == "osm_incline"
        assert steepest["percent"] == pytest.approx(4.0)
        assert route["segments"][steepest["segment_index"]]["incline_percent"] == pytest.approx(4.0)

    def test_a_slope_limit_applies_to_estimated_gradients(self, sloped_client: TestClient) -> None:
        # Steps allowed, so the only thing separating these two answers is the
        # 1.5% limit against the crossing's ~1.6% estimated climb.
        base = {"base": "wheelchair", "exclude_steps": False}
        free = compare(sloped_client, profile="custom", custom=base)["accessible_route"]
        limited = compare(
            sloped_client, profile="custom", custom={**base, "max_incline_percent": 1.5}
        )

        def steepest_estimated_climb(route: dict[str, Any]) -> float:
            climbs = [
                segment["derived_grade_percent"]
                for segment in route["segments"]
                if segment["incline_percent"] is None and segment["derived_grade_percent"]
            ]
            return max(climbs, default=0.0)

        assert steepest_estimated_climb(free) > 1.5
        assert steepest_estimated_climb(limited["accessible_route"]) <= 1.5
        # Regression (D4): the limit is repeated exactly as it was sent.
        assert "above 1.5%" in limited["profile_description"]


class TestCustomProfile:
    def test_it_accepts_overrides(self, client: TestClient) -> None:
        body = compare(
            client,
            profile="custom",
            custom={"base": "wheelchair", "exclude_steps": False},
        )

        assert body["profile"] == "custom"
        assert body["accessible_route"] is not None

    def test_allowing_stairs_can_shorten_the_route(self, client: TestClient) -> None:
        strict = compare(client, profile="wheelchair")["accessible_route"]["distance_m"]
        relaxed = compare(
            client,
            profile="custom",
            custom={"base": "wheelchair", "exclude_steps": False},
        )["accessible_route"]["distance_m"]

        assert relaxed <= strict

    def test_a_custom_profile_without_options_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": SYNTHETIC_REGION_SLUG,
                "origin": A,
                "destination": D,
                "profile": "custom",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "custom_profile_required"


class TestFailurePaths:
    def test_an_unknown_region_is_a_404_that_says_what_to_do(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={"region": "atlantis", "origin": A, "destination": D, "profile": "wheelchair"},
        )

        assert response.status_code == 404
        assert response.json()["code"] == "no_active_dataset"

    def test_a_point_far_off_the_network_is_refused_with_a_reason(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": SYNTHETIC_REGION_SLUG,
                "origin": {"longitude": -80.60, "latitude": 43.40},
                "destination": D,
                "profile": "wheelchair",
            },
        )

        assert response.status_code == 422
        assert "mapped path" in response.json()["message"]

    @pytest.mark.parametrize(
        "coordinate",
        [
            {"longitude": 200.0, "latitude": 43.47},
            {"longitude": -80.5, "latitude": 91.0},
        ],
    )
    def test_out_of_range_coordinates_are_rejected_by_the_schema(
        self, client: TestClient, coordinate: dict[str, float]
    ) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": SYNTHETIC_REGION_SLUG,
                "origin": coordinate,
                "destination": D,
                "profile": "wheelchair",
            },
        )

        assert response.status_code == 422
        assert response.json()["details"]

    def test_an_unknown_profile_is_rejected_by_the_schema(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": SYNTHETIC_REGION_SLUG,
                "origin": A,
                "destination": D,
                "profile": "hovercraft",
            },
        )

        assert response.status_code == 422

    def test_an_overlong_region_slug_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": "a" * 200,
                "origin": A,
                "destination": D,
                "profile": "wheelchair",
            },
        )

        assert response.status_code == 422

    def test_a_region_slug_with_injection_characters_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={
                "region": "waterloo'; DROP TABLE graph_edges;--",
                "origin": A,
                "destination": D,
                "profile": "wheelchair",
            },
        )

        assert response.status_code == 422

    def test_an_error_body_never_leaks_internals(self, client: TestClient) -> None:
        response = client.post(
            COMPARE,
            json={"region": "atlantis", "origin": A, "destination": D, "profile": "wheelchair"},
        )
        body = response.text.lower()

        assert "postgresql" not in body
        assert "password" not in body
        assert "traceback" not in body


class TestGraphCaching:
    def test_a_second_request_reuses_the_loaded_graph(self, client: TestClient) -> None:
        # Keyed by dataset version, which is immutable — so this can never serve
        # a stale network.
        compare(client)
        repository = client.app.state.graph_repository  # type: ignore[attr-defined]
        cached = repository.cached_dataset_ids()

        compare(client)
        assert repository.cached_dataset_ids() == cached
        assert len(cached) == 1

    def test_a_switch_mid_request_cannot_label_one_datasets_route_with_another(
        self, seeded_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression: the endpoint took its graph from one read of "the active
        # dataset" and its provenance from a second. An activation committed
        # between the two labelled a route computed on the old network with the
        # new network's id. Here the switch lands exactly in that gap.
        served = asyncio.run(
            _load_then_switch(seeded_database_url), loop_factory=selector_loop_factory()
        )

        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=seeded_database_url,
            allowed_origins=("http://localhost:3000",),
            log_level="WARNING",
            log_format="console",
        )
        with TestClient(create_app(settings)) as test_client:

            async def graph_read_before_the_switch(*_: object) -> RoutableGraph:
                return served

            repository = test_client.app.state.graph_repository  # type: ignore[attr-defined]
            monkeypatch.setattr(repository, "active_graph", graph_read_before_the_switch)
            body = compare(test_client)

        assert body["dataset"]["dataset_id"] == str(served.dataset_id)


async def _load_then_switch(database_url: str) -> RoutableGraph:
    """The live graph as a request would have loaded it, then a new dataset goes live."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repository = GraphRepository()
            served = await repository.active_graph(session, SYNTHETIC_REGION_SLUG)
            await load_synthetic_dataset(session)
            await session.commit()
            return served
    finally:
        await engine.dispose()
