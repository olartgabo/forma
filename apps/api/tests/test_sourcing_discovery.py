"""Automatic research preserves separate mapped places and online evidence."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forma_api.main import create_app
from forma_api.model_gateway import GatewayError
from forma_api.projects import ProjectStore
from forma_api.routes.nearby import nearby_router
from forma_api.routes.sourcing import sourcing_router, table
from forma_api.sourcing import (
    OfferObservation,
    ResearchRequest,
    ResearchRun,
    SourcingUsage,
)
from forma_api.sourcing_discovery import NearbyDiscoveryGateway, NearbyMetaGateway
from forma_api.sourcing_gateway import PendingResearch
from forma_api.sourcing_location import (
    LocationChoice,
    LocationSearchResponse,
    LocationServiceError,
    NearbyPlace,
    NearbyResponse,
)


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch):
    for name in ("MODEL_API_KEY", "META_API_KEY", "MUSE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


LOCATION = {
    "latitude": 37.775,
    "longitude": -122.419,
    "accuracy_m": None,
    "location_basis": "city_center",
    "label": "San Francisco",
    "country_code": "US",
    "confirmed": True,
    "transfer_consented": True,
}


def request():
    return ResearchRequest(
        expected_revision_id="inventory-one",
        idempotency_key="nearby-one",
        item="scissors",
        area="San Francisco",
        currency="USD",
        location=LOCATION,
    )


def mapped():
    return NearbyResponse(
        status="found",
        message="Branch stock unverified",
        places=(
            NearbyPlace(
                id="node/1",
                name="Local hardware",
                latitude=37.775,
                longitude=-122.419,
                distance_m=0,
                address="Market Street",
                website="https://hardware.example/",
                osm_url="https://www.openstreetmap.org/node/1",
                category="hardware",
            ),
        ),
    )


def test_discovery_only_uses_mapped_websites_and_separates_prices():
    calls = []
    offer = OfferObservation(
        title="Scissors",
        url="https://hardware.example/scissors",
        price="12.50",
        currency="USD",
        price_status="listed",
        location="Online offer; nearby branch stock unverified",
    )
    gateway = NearbyDiscoveryGateway(
        lambda body: mapped(), lambda *args: calls.append(args) or (offer,)
    )
    offers, usage = gateway.research(request())
    assert calls == [("scissors", "USD", ("https://hardware.example/",))]
    assert offers == (offer,) and usage is None
    assert gateway.places[0].name == "Local hardware"


def test_map_failure_is_known_failure_not_unknown_model_outcome():
    def fail(body):
        raise ValueError("public service failure")

    with pytest.raises(GatewayError) as error:
        NearbyDiscoveryGateway(fail).research(request())
    assert error.value.code == "discovery_failed"


def test_empty_maps_do_not_fetch_retail_pages():
    gateway = NearbyDiscoveryGateway(
        lambda body: NearbyResponse(status="empty", message="No mapped places"),
        lambda *args: pytest.fail("No retailer should be requested"),
    )
    assert gateway.research(request()) == ((), None)
    assert "No mapped retailer websites" in gateway.message


def test_meta_coordinator_supplies_mapped_places_without_fetching_retailers():
    calls = []

    class Meta:
        def research(self, body, *, places):
            calls.append((body, places))
            raise PendingResearch("resp_nearby", SourcingUsage(input_tokens=2))

    gateway = NearbyMetaGateway(Meta(), lambda body: mapped())
    with pytest.raises(PendingResearch):
        gateway.research(request())
    assert calls == [(request(), mapped().places)]
    assert gateway.places == mapped().places
    assert gateway.message == mapped().message


def test_known_map_failure_allows_one_area_research_but_unexpected_does_not():
    calls = []

    class Meta:
        def research(self, body, *, places):
            calls.append(places)
            return (), SourcingUsage(input_tokens=2)

    def known(body):
        raise LocationServiceError("service unavailable")

    gateway = NearbyMetaGateway(Meta(), known)
    assert gateway.research(request())[0] == ()
    assert calls == [()] and "unavailable" in gateway.message

    def unexpected(body):
        raise RuntimeError("adapter defect")

    with pytest.raises(GatewayError) as error:
        NearbyMetaGateway(Meta(), unexpected).research(request())
    assert error.value.code == "discovery_failed" and calls == [()]


def test_scoped_routes_and_automatic_research_do_not_change_project(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    token = "a" * 32
    app = create_app(tmp_path, {"owner": token, "other": "b" * 32})
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + token}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"goal": "stand", "idempotency_key": "project-one"},
    ).json()["project"]
    lookup_calls = []
    # Isolated router guarantees injected public transport and no model call.
    isolated = FastAPI()
    isolated.include_router(
        nearby_router(
            ProjectStore(tmp_path),
            lambda: "owner",
            geocode=lambda city: (
                lookup_calls.append(city)
                or LocationSearchResponse(
                    choices=(
                        LocationChoice(
                            id="relation/1",
                            label=city,
                            latitude=37.775,
                            longitude=-122.419,
                        ),
                    )
                )
            ),
            discover=lambda body: mapped(),
        ),
        prefix="/api/projects",
    )
    maps = TestClient(isolated)
    base = f"/api/projects/{project['id']}/sourcing"
    assert (
        maps.post(
            base + "/locations",
            json={"city": "San Francisco", "transfer_consented": False},
        ).status_code
        == 422
    )
    assert lookup_calls == []
    assert (
        maps.post(
            base + "/locations",
            json={"city": "San Francisco", "transfer_consented": True},
        ).json()["choices"][0]["label"]
        == "San Francisco"
    )
    assert (
        maps.post(base + "/nearby", json={"location": LOCATION}).json()["places"][0][
            "id"
        ]
        == "node/1"
    )
    monkeypatch.setattr(
        "forma_api.sourcing_discovery.NearbyDiscoveryGateway",
        lambda: NearbyDiscoveryGateway(lambda body: mapped(), lambda *args: ()),
    )
    payload = {**request().model_dump(), "expected_revision_id": project["revision_id"]}
    response = client.post(base + "/research", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    run = response.json()
    assert (
        run["status"] == "no_verified_results"
        and run["nearby_places"][0]["name"] == "Local hardware"
    )
    assert run["usage"] is None and run["provider_response_id"] is None
    assert (
        client.post(base + "/research", headers=headers, json=payload).json()[
            "replayed"
        ]
        is True
    )
    assert (
        client.get(f"/api/projects/{project['id']}", headers=headers).json() == project
    )
    assert (
        client.post(
            base + "/research",
            headers={"Authorization": "Bearer " + "b" * 32},
            json=payload,
        ).status_code
        == 404
    )


@pytest.fixture
def scoped_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    def no_meta():
        pytest.fail("A public recovery must never contact Meta")

    monkeypatch.setattr("forma_api.routes.sourcing.default_gateway_factory", no_meta)
    client = TestClient(create_app(tmp_path, {"owner": "a" * 32}))
    headers = {"Authorization": "Bearer " + "a" * 32}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"goal": "stand", "idempotency_key": "project-one"},
    ).json()["project"]
    return client, headers, project, ProjectStore(tmp_path)


def stale_receipt(runtime, kind, status="running", legacy=False):
    _, _, project, store = runtime
    run = ResearchRun(
        id="research-stale",
        project_id=project["id"],
        revision_id=project["revision_id"],
        kind=kind,
        status=status,
        observed_at=(datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat(),
        item="scissors",
        area="San Francisco",
        currency="USD",
    )
    body = run.model_dump_json(exclude={"kind"} if legacy else set())
    with store.transaction() as connection:
        table(connection)
        connection.execute(
            "INSERT INTO sourcing_runs VALUES (?,?,?,?,?)",
            (run.id, project["id"], "stale-request", "old-digest", body),
        )
    return run, body


def meta_client(runtime, monkeypatch, meta):
    _, _, _, store = runtime
    monkeypatch.setattr(
        "forma_api.sourcing_discovery.NearbyMetaGateway",
        lambda gateway: NearbyMetaGateway(gateway, lambda body: mapped()),
    )
    app = FastAPI()
    app.include_router(
        sourcing_router(store, lambda: "owner", lambda: meta), prefix="/api/projects"
    )
    return TestClient(app)


def test_consented_nearby_pending_and_completed_poll_keep_places_and_identity(
    scoped_runtime, monkeypatch
):
    _, _, project, store = scoped_runtime

    class Meta:
        posts = 0
        gets = 0

        def research(self, body, *, places):
            self.posts += 1
            assert places == mapped().places
            # Reservation must already be durable before the sole paid POST.
            with store.transaction() as connection:
                saved = ResearchRun.model_validate_json(
                    connection.execute("SELECT body FROM sourcing_runs").fetchone()[0]
                )
            assert saved.kind == "meta" and saved.status == "running"
            raise PendingResearch("resp_nearby", SourcingUsage(input_tokens=3))

        def poll(self, response_id, body):
            self.gets += 1
            assert response_id == "resp_nearby"
            assert body.location is None
            assert (body.item, body.area, body.currency) == (
                "scissors",
                "San Francisco",
                "USD",
            )
            return (), SourcingUsage(input_tokens=20, output_tokens=5)

    meta = Meta()
    client = meta_client(scoped_runtime, monkeypatch, meta)
    base = f"/api/projects/{project['id']}/sourcing/research"
    payload = {
        **request().model_dump(),
        "expected_revision_id": project["revision_id"],
        "provider_transfer_consented": True,
    }
    run = client.post(base, json=payload).json()
    assert run["kind"] == "meta" and run["status"] == "running"
    assert run["provider_response_id"] == "resp_nearby"
    assert run["nearby_places"][0]["id"] == "node/1"
    assert run["discovery_message"] == mapped().message
    assert client.post(base, json=payload).json()["replayed"]
    assert (
        client.post(base, json={**payload, "idempotency_key": "fresh-key"}).status_code
        == 409
    )
    reloaded = meta_client(scoped_runtime, monkeypatch, meta)
    final = reloaded.get(base + "/" + run["id"]).json()
    assert final["status"] == "no_verified_results"
    assert final["nearby_places"] == run["nearby_places"]
    assert final["discovery_message"] == run["discovery_message"]
    assert final["usage"]["input_tokens"] == 20
    assert meta.posts == 1 and meta.gets == 1
    original, headers, _, _ = scoped_runtime
    assert (
        original.get(f"/api/projects/{project['id']}", headers=headers).json()
        == project
    )


def test_consented_nearby_unknown_never_expires_as_public_or_retries(
    scoped_runtime, monkeypatch
):
    _, _, project, store = scoped_runtime

    class Meta:
        posts = 0

        def research(self, body, *, places):
            self.posts += 1
            raise GatewayError("timeout")

    meta = Meta()
    client = meta_client(scoped_runtime, monkeypatch, meta)
    base = f"/api/projects/{project['id']}/sourcing/research"
    payload = {
        **request().model_dump(),
        "expected_revision_id": project["revision_id"],
        "provider_transfer_consented": True,
    }
    run = client.post(base, json=payload).json()
    assert run["kind"] == "meta" and run["status"] == "outcome_unknown"
    assert run["nearby_places"][0]["id"] == "node/1"
    # Even an old Meta receipt cannot use the public-service expiry escape hatch.
    with store.transaction() as connection:
        aged = ResearchRun.model_validate(run).model_copy(
            update={
                "observed_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=121)
                ).isoformat()
            }
        )
        connection.execute(
            "UPDATE sourcing_runs SET body=? WHERE id=?",
            (aged.model_dump_json(), run["id"]),
        )
    assert client.get(base + "/" + run["id"]).json()["status"] == "outcome_unknown"
    assert (
        client.post(base, json={**payload, "idempotency_key": "fresh-key"}).status_code
        == 409
    )
    assert client.post(base, json=payload).json()["replayed"]
    assert meta.posts == 1


def test_consented_nearby_configuration_preflight_does_not_reserve(scoped_runtime):
    client, headers, project, store = scoped_runtime
    # Restore the real local factory: absent credentials must fail before OSM or POST.
    from forma_api.sourcing_gateway import default_gateway_factory

    app = FastAPI()
    app.include_router(
        sourcing_router(store, lambda: "owner", default_gateway_factory),
        prefix="/api/projects",
    )
    client = TestClient(app)
    response = client.post(
        f"/api/projects/{project['id']}/sourcing/research",
        json={
            **request().model_dump(),
            "expected_revision_id": project["revision_id"],
            "provider_transfer_consented": True,
        },
    )
    assert response.status_code == 503
    with store.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) FROM sourcing_runs").fetchone()[0] == 0
        )


@pytest.mark.parametrize("kind", ["public_discovery", "supplier_page"])
def test_stale_public_run_recovers_without_external_call(
    scoped_runtime, monkeypatch, kind
):
    client, headers, project, _ = scoped_runtime
    run, _ = stale_receipt(scoped_runtime, kind)
    base = f"/api/projects/{project['id']}/sourcing"
    recovered = client.get(base + "/research/" + run.id, headers=headers)
    assert recovered.status_code == 200
    assert (
        recovered.json()["status"] == "failed" and "retry" in recovered.json()["error"]
    )
    assert recovered.json()["kind"] == kind
    assert client.get(base + "/needs", headers=headers).json()["pending_run_id"] is None
    # A fresh explicit public request is now possible; the old receipt is retained.
    monkeypatch.setattr(
        "forma_api.sourcing_discovery.NearbyDiscoveryGateway",
        lambda: NearbyDiscoveryGateway(lambda body: mapped(), lambda *args: ()),
    )
    payload = {
        **request().model_dump(),
        "expected_revision_id": project["revision_id"],
        "idempotency_key": "new-public-request",
    }
    new = client.post(base + "/research", headers=headers, json=payload)
    assert new.status_code == 200 and new.json()["kind"] == "public_discovery"
    assert (
        client.get(base + "/research/" + run.id, headers=headers).json()["status"]
        == "failed"
    )
    assert (
        client.get(f"/api/projects/{project['id']}", headers=headers).json() == project
    )


@pytest.mark.parametrize("status", ["running", "outcome_unknown"])
def test_legacy_meta_receipts_remain_blocked_and_unchanged(scoped_runtime, status):
    client, headers, project, store = scoped_runtime
    run, original = stale_receipt(scoped_runtime, "meta", status, legacy=True)
    base = f"/api/projects/{project['id']}/sourcing"
    saved = client.get(base + "/research/" + run.id, headers=headers).json()
    assert saved["kind"] == "meta" and saved["status"] == status
    payload = {
        **request().model_dump(),
        "expected_revision_id": project["revision_id"],
        "idempotency_key": "new-public-request",
    }
    assert (
        client.post(base + "/research", headers=headers, json=payload).status_code
        == 409
    )
    with store.transaction() as connection:
        assert (
            connection.execute(
                "SELECT body FROM sourcing_runs WHERE id=?", (run.id,)
            ).fetchone()[0]
            == original
        )


def test_unexpected_public_exception_fails_without_unknown_billing_block(
    scoped_runtime, monkeypatch
):
    client, headers, project, _ = scoped_runtime

    class BrokenPublicGateway:
        def research(self, body):
            raise RuntimeError("Unexpected public adapter failure")

    monkeypatch.setattr(
        "forma_api.sourcing_discovery.NearbyDiscoveryGateway", BrokenPublicGateway
    )
    base = f"/api/projects/{project['id']}/sourcing"
    payload = {**request().model_dump(), "expected_revision_id": project["revision_id"]}
    response = client.post(base + "/research", headers=headers, json=payload)
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "retry" in response.json()["error"]
    assert client.get(base + "/needs", headers=headers).json()["pending_run_id"] is None


def test_late_public_worker_cannot_overwrite_stale_run_recovery(
    scoped_runtime, monkeypatch
):
    client, headers, project, store = scoped_runtime
    clock = [datetime.now(timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr("forma_api.routes.sourcing.datetime", Clock)
    base = f"/api/projects/{project['id']}/sourcing"

    class DelayedGateway:
        def research(self, body):
            with store.transaction() as connection:
                run_id = connection.execute(
                    "SELECT id FROM sourcing_runs WHERE project_id=?", (project["id"],)
                ).fetchone()[0]
            clock[0] += timedelta(seconds=121)
            expired = client.get(base + "/research/" + run_id, headers=headers)
            assert expired.json()["status"] == "failed"
            return (), None

    monkeypatch.setattr(
        "forma_api.sourcing_discovery.NearbyDiscoveryGateway", DelayedGateway
    )
    response = client.post(
        base + "/research",
        headers=headers,
        json={**request().model_dump(), "expected_revision_id": project["revision_id"]},
    )
    assert response.status_code == 200
    assert (
        response.json()["status"] == "failed"
        and "interrupted" in response.json()["error"]
    )
    saved = client.get(
        base + "/research/" + response.json()["id"], headers=headers
    ).json()
    assert saved == response.json()
