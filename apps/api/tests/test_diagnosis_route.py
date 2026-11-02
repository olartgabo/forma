import base64
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


def evidence_rows(tmp_path):
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        return connection.execute(
            "SELECT id, project_id, version_id, asset_id, body "
            "FROM progress_evidence ORDER BY rowid"
        ).fetchall()


def get_progress(client, p, version_id, auth=AUTH):
    return client.get(
        f"/api/projects/{p['id']}/versions/{version_id}/progress", headers=auth
    )


def active_payload(p, media, version, **overrides):
    values = {
        "expected_active_version_id": version.version_id,
        "current_operation_id": version.plan.operations[0].id,
    }
    values.update(overrides)
    return body(p, media, **values)


def test_photo_only_success_is_readonly(client, monkeypatch, tmp_path):
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
    assert evidence_rows(tmp_path) == []


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


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "visible_observations": [],
            "hypotheses": [],
            "questions_or_measurements": [],
        },
        {
            "visible_observations": [" ", "\t"],
            "hypotheses": ["\n"],
            "questions_or_measurements": ["  "],
        },
    ],
)
def test_empty_or_whitespace_diagnosis_is_safe_502_and_readonly(
    client, monkeypatch, overrides
):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final(**overrides))
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (
        502,
        "invalid_response",
    )
    assert response.json() == {
        "code": "invalid_response",
        "message": "Model provider returned an unusable response; retry",
    }
    assert "SECRET" not in response.text
    assert len(fake.calls) == 1
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before


def test_question_only_unknown_diagnosis_succeeds_and_is_readonly(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    question = "Can you measure the distance from the slot to the edge?"
    fake = Fake(
        final(
            visible_observations=[],
            hypotheses=[],
            questions_or_measurements=[question],
            failure_type="unknown",
        )
    )
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call(client, p, body(p, media))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["diagnosis"]["failure_type"] == "unknown"
    assert result["diagnosis"]["visible_observations"] == []
    assert result["diagnosis"]["hypotheses"] == []
    assert result["diagnosis"]["questions_or_measurements"] == [question]
    assert result["diagnosis"]["affected_ids"] == []
    assert len(fake.calls) == 1
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
    # Only the new evidence row is added; no other progress/plan state changes.
    rows = evidence_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3] == media["id"]
    snapshot = get_progress(client, p, version.version_id).json()
    assert snapshot["events"] == []
    assert snapshot["material_transactions"] == []
    assert snapshot["completed_operation_ids"] == []
    assert len(snapshot["evidence"]) == 1


def test_active_diagnosis_persists_evidence_visible_on_reload(
    client, monkeypatch, tmp_path
):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key="upload-diag-persist")
    operation = version.plan.operations[0]
    part = version.plan.parts[0]
    fake = Fake(final(affected_ids=[operation.id, part.id], failure_type="torn_slot"))
    install(monkeypatch, fake)
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        media_before = connection.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    response = call(client, p, active_payload(p, media, version))
    assert response.status_code == 200, response.text
    snapshot_response = get_progress(client, p, version.version_id)
    assert snapshot_response.status_code == 200
    evidence = snapshot_response.json()["evidence"]
    assert len(evidence) == 1
    item = evidence[0]
    assert item["kind"] == "model_interpretation"
    assert item["provenance"] == "model"
    assert item["verification_state"] == "vision_observed"
    assert item["asset_id"] == media["id"]
    assert item["operation_ids"] == [operation.id]
    assert item["part_ids"] == [part.id]
    assert "torn_slot" in item["description"]
    assert "A tear is visible" in item["description"]
    rows = evidence_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][3] == media["id"]
    assert base64.b64encode(photo_bytes()).decode() not in rows[0][4]
    assert "data:image" not in rows[0][4]
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            == media_before
        )
    assert get_progress(client, p, version.version_id, OTHER).status_code == 404


def test_identical_diagnosis_idempotent_and_different_appends(
    client, monkeypatch, tmp_path
):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key="upload-diag-idempotent")
    fake = Fake(
        final(failure_type="torn_slot"),
        final(failure_type="torn_slot"),
        final(
            failure_type="damaged_part",
            visible_observations=["A crack is visible"],
        ),
    )
    install(monkeypatch, fake)
    payload = active_payload(p, media, version)
    assert call(client, p, payload).status_code == 200
    first = evidence_rows(tmp_path)
    assert len(first) == 1
    assert call(client, p, payload).status_code == 200
    assert evidence_rows(tmp_path) == first
    assert call(client, p, payload).status_code == 200
    rows = evidence_rows(tmp_path)
    assert len(rows) == 2
    assert rows[0] == first[0]
    assert rows[1][0] != rows[0][0]
    assert "damaged_part" in rows[1][4]


def test_active_failure_paths_persist_nothing(client, monkeypatch, tmp_path):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key="upload-diag-failures")
    fake = Fake(final())
    install(monkeypatch, fake)
    assert (
        call(
            client,
            p,
            active_payload(p, media, version, provider_transfer_consented=False),
        ).status_code
        == 422
    )
    assert (
        call(
            client,
            p,
            active_payload(
                p, media, version, expected_active_version_id="version-other"
            ),
        ).status_code
        == 409
    )
    assert (
        call(
            client,
            p,
            active_payload(p, media, version, current_operation_id="op-missing"),
        ).status_code
        == 422
    )
    install(monkeypatch, Fake(GatewayError("timeout")))
    assert call(client, p, active_payload(p, media, version)).status_code == 504
    install(
        monkeypatch,
        Fake(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "not json"},
                    }
                ]
            }
        ),
    )
    assert call(client, p, active_payload(p, media, version)).status_code == 502
    install(
        monkeypatch,
        Fake(
            final(
                visible_observations=[],
                hypotheses=[],
                questions_or_measurements=[],
            )
        ),
    )
    assert call(client, p, active_payload(p, media, version)).status_code == 502
    install(monkeypatch, Fake(final(affected_ids=["part-invented"])))
    assert call(client, p, active_payload(p, media, version)).status_code == 502
    assert evidence_rows(tmp_path) == []
    assert fake.calls == []


@pytest.mark.parametrize(
    "mutate,status", [("change", 409), ("delete_project", 404), ("delete_media", 404)]
)
def test_active_post_call_stale_or_deletion_persists_nothing(
    client, monkeypatch, tmp_path, mutate, status
):
    p, version = _active_project(client, tmp_path)
    media = upload(client, p, key=f"upload-diag-postcall-{mutate}")
    fake = Fake(final(), on_call=lambda: _mutate(tmp_path, p["id"], mutate))
    install(monkeypatch, fake)
    response = call(client, p, active_payload(p, media, version))
    assert response.status_code == status, response.text
    assert evidence_rows(tmp_path) == []


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
