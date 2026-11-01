import json
import sqlite3
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_plans import AUTH, OTHER, TOKENS, prepared

from forma_api import diagnosis_runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway
from forma_api.plans import PlanService
from forma_api.projects import ProjectStore


class Fake:
    def __init__(self, *responses, on_call=None):
        self.responses = list(responses)
        self.calls = []
        self.on_call = on_call

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        if self.on_call:
            self.on_call()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def final(**overrides):
    value = {
        "visible_observations": ["A tear is visible"],
        "hypotheses": ["The slot may be weak"],
        "questions_or_measurements": ["Measure the edge distance"],
        "affected_ids": [],
        "failure_type": "unknown",
    }
    value.update(overrides)
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
        ]
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def project(client, key="project-001"):
    response = client.post(
        "/api/projects", headers=AUTH, json={"goal": "stand", "idempotency_key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]


def photo_bytes(format="PNG"):
    with Image.new("RGB", (12, 8), "white") as image:
        output = BytesIO()
        image.save(output, format=format)
        return output.getvalue()


def upload(client, p, format="PNG", mime="image/png", key="upload-001"):
    response = client.post(
        f"/api/projects/{p['id']}/media",
        content=photo_bytes(format),
        headers={**AUTH, "Idempotency-Key": key, "Content-Type": mime},
    )
    assert response.status_code == 201, response.text
    return response.json()["media"]


def install(monkeypatch, fake):
    counter = {"factory": 0}

    def factory():
        counter["factory"] += 1
        return MetaGateway(fake)

    monkeypatch.setattr(diagnosis_runtime, "default_gateway_factory", factory)
    return counter


def body(p, media, **overrides):
    value = {
        "media_id": media["id"],
        "expected_revision_id": p["revision_id"],
        "reported_problem": "The slot tore",
        "provider_transfer_consented": True,
    }
    value.update(overrides)
    return value


def call(client, p, payload, auth=AUTH):
    return client.post(f"/api/projects/{p['id']}/diagnose", json=payload, headers=auth)


def test_photo_only_success_is_readonly(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    assert counter["factory"] == 0
    spec = client.get("/openapi.json")
    assert "/api/projects/{project_id}/diagnose" in spec.json()["paths"]
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call(client, p, body(p, media))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project_id"] == p["id"]
    assert result["active_version_id"] is None
    assert result["diagnosis"]["affected_ids"] == []
    assert result["diagnosis"]["visible_observations"] == ["A tear is visible"]
    assert result["diagnostics"]["model"] == "muse-spark-1.3"
    assert counter["factory"] == 1 and len(fake.calls) == 1
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before


def test_photo_only_invented_affected_ids_are_invalid_response(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final(affected_ids=["part-invented"]))
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (
        502,
        "invalid_response",
    )
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before


def test_gates_have_no_dispatch(client, monkeypatch, tmp_path):
    p = project(client)
    other_project = project(client, "project-002")
    media = upload(client, p)
    webp_project = project(client, "project-003")
    webp = upload(client, webp_project, "WEBP", "image/webp", "upload-webp")
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    path = f"/api/projects/{p['id']}/diagnose"
    assert client.post(path, json=body(p, media)).status_code == 401
    assert call(client, p, body(p, media), OTHER).status_code == 404
    assert call(client, other_project, body(other_project, media)).status_code == 404
    assert call(client, p, body(p, media, media_id="media-missing")).status_code == 404
    for payload in (
        body(p, media, provider_transfer_consented=False),
        {k: v for k, v in body(p, media).items() if k != "provider_transfer_consented"},
        body(p, media, reported_problem="   "),
        body(p, media, reported_problem="x" * 1001),
        body(p, media, expected_active_version_id="version-1"),
        body(p, media, current_operation_id="op-1"),
    ):
        response = call(client, p, payload)
        assert response.status_code == 422, response.text
    stale = call(client, p, body(p, media, expected_revision_id="inventory-stale"))
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_version")
    assert call(client, webp_project, body(webp_project, webp)).status_code == 415
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE media SET body=? WHERE id=?",
            (b"\xff\xd8\xff" + b"\x00" * 5_000_000, media["id"]),
        )
    assert call(client, p, body(p, media)).status_code == 413
    assert counter["factory"] == 0 and fake.calls == []


@pytest.mark.parametrize("value", [1, "true", None, []])
def test_nonboolean_consent_rejected_without_dispatch(client, monkeypatch, value):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    response = call(client, p, body(p, media, provider_transfer_consented=value))
    assert response.status_code == 422
    assert response.json() == {
        "code": "validation_error",
        "message": "Request validation failed",
    }
    assert counter["factory"] == 0 and fake.calls == []


def test_extra_trusted_fields_rejected(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    for extra in ({"snapshot": {}}, {"provider_key": "secret"}, {"plan": {}}):
        response = call(client, p, {**body(p, media), **extra})
        assert response.status_code == 422
        assert "secret" not in response.text
    assert counter["factory"] == 0 and fake.calls == []


def _active_project(client, tmp_path):
    project_data, preview, context = prepared(client)
    store = ProjectStore(tmp_path)
    service = PlanService(store, allow_synthetic=True)
    result = service.compile_preview("alice", project_data["id"], preview, **context)
    assert result.status == "accepted", result.model_dump()
    version = result.version
    base = f"/api/projects/{project_data['id']}"
    activated = client.post(
        f"{base}/plans/{version.version_id}/activate",
        headers=AUTH,
        json={
            "expected_revision_id": project_data["revision_id"],
            "idempotency_key": "activate-diag-1",
            "user_approved": True,
        },
    )
    assert activated.status_code == 200, activated.text
    return activated.json()["project"], version


def test_active_operation_context_and_valid_affected_id(client, monkeypatch, tmp_path):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key="upload-diag-active")
    operation = version.plan.operations[0]
    fake = Fake(final(affected_ids=[operation.id], failure_type="torn_slot"))
    install(monkeypatch, fake)
    payload = body(
        p,
        media,
        expected_active_version_id=version.version_id,
        current_operation_id=operation.id,
    )
    response = call(client, p, payload)
    assert response.status_code == 200, response.text
    assert response.json()["diagnosis"]["affected_ids"] == [operation.id]
    serialized = fake.calls[0][1]["messages"][1]["content"][0]["text"]
    assert operation.id in serialized
    assert '"active_plan"' in serialized
    assert version.version_id in serialized


def test_plan_and_operation_mismatches_have_no_dispatch(client, monkeypatch, tmp_path):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key="upload-diag-mismatch")
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    wrong_version = call(
        client,
        p,
        body(
            p,
            media,
            expected_active_version_id="version-other",
            current_operation_id=version.plan.operations[0].id,
        ),
    )
    assert (wrong_version.status_code, wrong_version.json()["code"]) == (
        409,
        "stale_version",
    )
    wrong_operation = call(
        client,
        p,
        body(
            p,
            media,
            expected_active_version_id=version.version_id,
            current_operation_id="op-missing",
        ),
    )
    assert wrong_operation.status_code == 422
    invented = Fake(final(affected_ids=["part-invented"]))
    install(monkeypatch, invented)
    response = call(
        client,
        p,
        body(
            p,
            media,
            expected_active_version_id=version.version_id,
            current_operation_id=version.plan.operations[0].id,
        ),
    )
    assert (response.status_code, response.json()["code"]) == (
        502,
        "invalid_response",
    )
    assert counter["factory"] == 0 and fake.calls == []


def test_provider_failure_redacted_and_state_immutable(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(GatewayError("timeout"))
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (504, "timeout")
    assert "SECRET" not in response.text
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before


def test_malformed_provider_output_is_safe(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "SECRET_PROVIDER_BODY not json"},
                }
            ]
        }
    )
    install(monkeypatch, fake)
    response = call(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (
        502,
        "invalid_response",
    )
    assert "SECRET_PROVIDER_BODY" not in response.text


def _mutate(tmp_path, project_id, mutate):
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        if mutate == "delete_project":
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return
        if mutate == "delete_media":
            connection.execute("DELETE FROM media WHERE project_id=?", (project_id,))
            return
        row = connection.execute(
            "SELECT body FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        data = json.loads(row[0])
        data["revision_id"] = "inventory-changed-during-call"
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(data), project_id)
        )


@pytest.mark.parametrize(
    "mutate,status", [("change", 409), ("delete_project", 404), ("delete_media", 404)]
)
def test_post_call_stale_or_deletion_is_not_returned(
    client, monkeypatch, tmp_path, mutate, status
):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final(), on_call=lambda: _mutate(tmp_path, p["id"], mutate))
    install(monkeypatch, fake)
    response = call(client, p, body(p, media))
    assert response.status_code == status, response.text
    assert "A tear is visible" not in response.text


def test_missing_key_is_safe_503(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    response = call(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (
        503,
        "provider_not_configured",
    )
