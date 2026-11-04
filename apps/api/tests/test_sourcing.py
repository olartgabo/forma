import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forma_api.main import create_app
from forma_api.model_gateway import GatewayError
from forma_api.projects import ProjectStore
from forma_api.routes.sourcing import sourcing_router
from forma_api.sourcing import OfferObservation, SourcingUsage

TOKEN = "a" * 32


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Scissors 21.99 USD. Starting fluid in navigation", ("21.99", "listed")),
        ("Starting at $10", (None, "partial_price")),
        ("Starting from USD 10", (None, "partial_price")),
        ("Starting $10", (None, "partial_price")),
        ("Starting USD 10", (None, "partial_price")),
        ("Deposit 10", (None, "partial_price")),
        ("DM for price", (None, "price_unknown")),
    ],
)
def test_starting_price_qualifier_requires_price_phrasing(text, expected):
    from forma_api.sourcing import price_status

    assert price_status("21.99", text) == expected


def test_supplier_page_is_explicit_scoped_idempotent_and_has_no_meta_consent(
    setup, monkeypatch
):
    _, client, headers, project = setup
    from forma_api.supplier_page import SupplierPageGateway

    calls = []
    url = "https://www.tramontinastore.com.bo/shop/example/scissors"
    html = '<h1>Scissors</h1><meta itemprop="priceCurrency" content="BOB"><meta itemprop="price" content="28.75">'
    gateway = SupplierPageGateway(lambda source: (calls.append(source) or source, html))
    monkeypatch.setattr("forma_api.supplier_page.SupplierPageGateway", lambda: gateway)
    path = f"/api/projects/{project['id']}/sourcing/research"
    request = body(
        project,
        source="supplier_page",
        supplier_url=url,
        provider_transfer_consented=False,
    )
    response = client.post(path, headers=headers, json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["offers"][0]["price"] == "28.75" and result["usage"] is None
    assert result["provider_response_id"] is None
    assert client.post(path, headers=headers, json=request).json()["replayed"]
    assert calls == [url]
    assert (
        client.get(f"/api/projects/{project['id']}", headers=headers).json() == project
    )
    assert (
        client.post(
            path, headers={"Authorization": "Bearer " + "b" * 32}, json=request
        ).status_code
        == 404
    )
    assert (
        client.post(
            path,
            headers=headers,
            json={
                **request,
                "idempotency_key": "stale-page",
                "expected_revision_id": "inventory-other",
            },
        ).status_code
        == 409
    )
    assert calls == [url]


@pytest.mark.parametrize(
    "override",
    [
        {"supplier_url": "https://evil.test/shop/a"},
        {"supplier_url": None},
        {"source": "suppliers", "supplier_url": "https://uyustus.com.bo/productos/a/"},
    ],
)
def test_supplier_page_url_contract_blocks_unapproved_sources(setup, override):
    _, client, headers, project = setup
    request = body(
        project,
        source="supplier_page",
        supplier_url="https://uyustus.com.bo/productos/a/",
        **{},
    )
    request.update(override)
    assert (
        client.post(
            f"/api/projects/{project['id']}/sourcing/research",
            headers=headers,
            json=request,
        ).status_code
        == 422
    )


class Gateway:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def research(self, request):
        self.calls += 1
        if self.fail:
            raise GatewayError("timeout")
        return (
            OfferObservation(
                title="Tape",
                url="https://shop.example/tape",
                price="20",
                currency="BOB",
                price_status="listed",
            ),
        ), SourcingUsage(input_tokens=4)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    app = create_app(tmp_path, {"owner": TOKEN, "other": "b" * 32})
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"goal": "stand", "idempotency_key": "create-1"},
    ).json()["project"]
    return tmp_path, client, headers, project


def body(project, **kw):
    return {
        **dict(
            expected_revision_id=project["revision_id"],
            idempotency_key="research-1",
            item="tape",
            area="La Paz",
            currency="BOB",
            provider_transfer_consented=True,
        ),
        **kw,
    }


def injected(tmp_path, gateway):
    app = FastAPI()
    app.include_router(
        sourcing_router(ProjectStore(tmp_path), lambda: "owner", lambda: gateway),
        prefix="/api/projects",
    )
    return TestClient(app)


def test_auth_scope_and_defaults(setup):
    _, client, headers, p = setup
    path = f"/api/projects/{p['id']}/sourcing/needs"
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": "Bearer " + "b" * 32}).status_code
        == 404
    )
    data = client.get(path, headers=headers).json()
    assert (
        data["needs"] == [] and data["marketplace_status"] == "authorization_required"
    )
    assert data["guidance"]


def test_consent_policy_stale_and_live_gate(setup):
    _, client, headers, p = setup
    path = f"/api/projects/{p['id']}/sourcing/research"
    for override, code in [
        ({"provider_transfer_consented": False}, 422),
        ({"source": "marketplace"}, 403),
        ({"expected_revision_id": "inventory-other"}, 409),
        ({}, 503),
    ]:
        response = client.post(path, headers=headers, json=body(p, **override))
        assert response.status_code == code, response.text
    assert client.get(f"/api/projects/{p['id']}", headers=headers).json() == p


def test_durable_replay_and_no_physical_writes(setup):
    path, original, headers, p = setup
    gateway = Gateway()
    client = injected(path, gateway)
    url = f"/api/projects/{p['id']}/sourcing/research"
    first = client.post(url, json=body(p))
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "succeeded" and result["item"] == "tape"
    assert client.post(url, json=body(p)).json()["replayed"]
    assert gateway.calls == 1
    assert client.post(url, json=body(p, item="scissors")).status_code == 409
    assert client.get(url + "/" + result["id"]).json()["id"] == result["id"]
    assert original.get(f"/api/projects/{p['id']}", headers=headers).json() == p


def test_unknown_blocks_new_keys_and_survives_restart(setup):
    path, _, _, p = setup
    gateway = Gateway(True)
    client = injected(path, gateway)
    url = f"/api/projects/{p['id']}/sourcing/research"
    result = client.post(url, json=body(p)).json()
    assert result["status"] == "outcome_unknown"
    client = injected(path, gateway)
    assert client.post(url, json=body(p)).json()["replayed"]
    assert (
        client.post(url, json=body(p, idempotency_key="new-key-123")).status_code == 409
    )
    assert gateway.calls == 1


def test_deletion_cascades_research(setup):
    path, original, headers, p = setup
    client = injected(path, Gateway())
    url = f"/api/projects/{p['id']}/sourcing/research"
    assert client.post(url, json=body(p)).status_code == 200
    assert (
        original.delete(
            f"/api/projects/{p['id']}",
            headers={**headers, "idempotency-key": "delete-1"},
        ).status_code
        == 200
    )
    with ProjectStore(path).transaction() as connection:
        assert (
            connection.execute("SELECT count(*) FROM sourcing_runs").fetchone()[0] == 0
        )


def test_pending_run_discoverable_after_reload(setup):
    path, original, headers, p = setup
    client = injected(path, Gateway(True))
    url = f"/api/projects/{p['id']}/sourcing/research"
    run = client.post(url, json=body(p)).json()
    needs = original.get(
        f"/api/projects/{p['id']}/sourcing/needs", headers=headers
    ).json()
    assert needs["pending_run_id"] == run["id"]


def test_fabrication_tool_gaps_preserve_engine_identity(setup, monkeypatch):
    from types import SimpleNamespace as N

    from forma_api import fabrication_runtime

    path, client, headers, p = setup
    with ProjectStore(path).transaction() as connection:
        project = ProjectStore.read(connection, "owner", p["id"])
        project = project.model_copy(update={"active_version_id": "version-active"})
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (project.model_dump_json(), p["id"]),
        )
    report = N(
        snapshot=N(inputs_sha256="a" * 64),
        operations=[
            N(
                status="blocked",
                operation_id="operation-cut",
                tools=[
                    N(tool="cutting", status="not_declared"),
                    N(tool="ruler", status="unknown"),
                ],
            )
        ],
    )
    monkeypatch.setattr(fabrication_runtime, "active_report", lambda *args: report)
    data = client.get(f"/api/projects/{p['id']}/sourcing/needs", headers=headers).json()
    assert len(data["needs"]) == 1
    assert data["needs"][0]["label"] == "cutting"
    assert (
        "version-active" in data["needs"][0]["reason"]
        and "a" * 64 in data["needs"][0]["reason"]
    )
    assert "Confirm possession" in data["needs"][0]["reason"]


@pytest.mark.parametrize(
    "code",
    ["invalid_response", "response_too_large", "provider_http_error", "network_error"],
)
def test_postdispatch_unusable_response_blocks_fresh_charge(setup, code):
    path, _, _, p = setup

    class FailedGateway:
        calls = 0

        def research(self, request):
            self.calls += 1
            raise GatewayError(code)

    gateway = FailedGateway()
    client = injected(path, gateway)
    url = f"/api/projects/{p['id']}/sourcing/research"
    first = client.post(url, json=body(p)).json()
    assert first["status"] == "outcome_unknown" and first["usage"] is None
    assert (
        client.post(url, json=body(p, idempotency_key="fresh-key-456")).status_code
        == 409
    )
    assert client.post(url, json=body(p)).json()["replayed"]
    assert gateway.calls == 1


def test_known_usage_survives_invalid_completed_response(setup):
    path, _, _, p = setup

    class FailedGateway:
        def research(self, request):
            error = GatewayError("invalid_response")
            error.sourcing_usage = SourcingUsage(input_tokens=17, output_tokens=9)
            raise error

    client = injected(path, FailedGateway())
    result = client.post(
        f"/api/projects/{p['id']}/sourcing/research", json=body(p)
    ).json()
    assert result["status"] == "outcome_unknown"
    assert (
        result["usage"]["input_tokens"] == 17 and result["usage"]["output_tokens"] == 9
    )


def test_background_identity_persists_and_reload_polls_without_new_generation(setup):
    from forma_api.sourcing_gateway import PendingResearch

    path, original, headers, p = setup

    class Background:
        posts = 0
        gets = 0

        def research(self, request):
            self.posts += 1
            raise PendingResearch("resp_background", SourcingUsage())

        def poll(self, response_id, request):
            self.gets += 1
            assert response_id == "resp_background"
            return (), SourcingUsage(input_tokens=20, output_tokens=4)

    gateway = Background()
    client = injected(path, gateway)
    url = f"/api/projects/{p['id']}/sourcing/research"
    run = client.post(url, json=body(p)).json()
    assert (
        run["status"] == "running" and run["provider_response_id"] == "resp_background"
    )
    assert client.post(url, json=body(p)).json()["replayed"]
    assert (
        client.post(url, json=body(p, idempotency_key="different-key")).status_code
        == 409
    )
    # A new router instance over the same durable store recovers by GET.
    reloaded = injected(path, gateway)
    final = reloaded.get(url + "/" + run["id"]).json()
    assert final["status"] == "no_verified_results"
    assert final["usage"]["input_tokens"] == 20
    assert reloaded.get(url + "/" + run["id"]).json() == final
    assert gateway.posts == 1 and gateway.gets == 1
    assert original.get(f"/api/projects/{p['id']}", headers=headers).json() == p


def test_poll_timeout_keeps_response_id_and_retrieval_can_resume(setup):
    from forma_api.sourcing_gateway import PendingResearch

    path, _, _, p = setup

    class Background:
        def research(self, request):
            raise PendingResearch("resp_recoverable", SourcingUsage())

        def poll(self, response_id, request):
            raise GatewayError("timeout")

    client = injected(path, Background())
    url = f"/api/projects/{p['id']}/sourcing/research"
    run = client.post(url, json=body(p)).json()
    recovered = client.get(url + "/" + run["id"]).json()
    assert recovered["status"] == "outcome_unknown"
    assert recovered["provider_response_id"] == "resp_recoverable"
    assert (
        client.post(url, json=body(p, idempotency_key="fresh-request")).status_code
        == 409
    )
