import json
import sqlite3
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from forma_api import intake_runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway

TOKENS = {"alice": "a" * 40, "bob": "b" * 40}
AUTH = {"Authorization": "Bearer " + TOKENS["alice"]}
OTHER = {"Authorization": "Bearer " + TOKENS["bob"]}


class Fake:
    def __init__(self, *responses, on_call=None):
        self.responses = iter(responses)
        self.calls = []
        self.on_call = on_call

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        if self.on_call:
            self.on_call()
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def final(content=None):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": content
                    or '{"labels":["cardboard sheet"],"measurement_source":"unknown",'
                    '"questions":["Measure thickness"]}'
                },
            }
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


def photo(format="PNG"):
    with Image.new("RGB", (12, 8), "white") as image:
        output = BytesIO()
        image.save(output, format=format)
        return output.getvalue()


def upload(client, p, format="PNG", mime="image/png", key="upload-001"):
    response = client.post(
        f"/api/projects/{p['id']}/media",
        content=photo(format),
        headers={**AUTH, "Idempotency-Key": key, "Content-Type": mime},
    )
    assert response.status_code == 201, response.text
    return response.json()["media"]


def install(monkeypatch, fake):
    counter = {"factory": 0}

    def factory():
        counter["factory"] += 1
        return MetaGateway(fake)

    monkeypatch.setattr(intake_runtime, "default_gateway_factory", factory)
    return counter


def body(p, media, **overrides):
    value = {
        "media_id": media["id"],
        "expected_revision_id": p["revision_id"],
        "provider_transfer_consented": True,
    }
    value.update(overrides)
    return value


def call_intake(client, p, payload, auth=AUTH):
    return client.post(f"/api/projects/{p['id']}/intake", json=payload, headers=auth)


def test_success_is_readonly_and_openapi_lists_route(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    assert counter["factory"] == 0
    spec = client.get("/openapi.json")
    assert "/api/projects/{project_id}/intake" in spec.json()["paths"]
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    response = call_intake(client, p, body(p, media))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project_id"] == p["id"]
    assert result["revision_id"] == p["revision_id"]
    assert result["media_id"] == media["id"]
    assert result["observation"] == {
        "labels": ["cardboard sheet"],
        "measurement_source": "unknown",
        "questions": ["Measure thickness"],
    }
    assert result["diagnostics"]["status"] == "ok"
    assert result["diagnostics"]["model"] == "muse-spark-1.3"
    assert isinstance(result["diagnostics"]["elapsed_ms"], int)
    assert counter["factory"] == 1 and len(fake.calls) == 1
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before
    assert client.get(f"/api/projects/{p['id']}/media", headers=AUTH).json()[
        "media"
    ] == [media]


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
def test_stored_jpeg_and_png_allowed(client, monkeypatch, format, mime):
    p = project(client)
    media = upload(client, p, format, mime)
    fake = Fake(final())
    install(monkeypatch, fake)
    assert call_intake(client, p, body(p, media)).status_code == 200
    assert len(fake.calls) == 1


def test_denials_have_zero_factory_or_provider_calls(client, monkeypatch, tmp_path):
    p = project(client)
    other_project = project(client, "project-002")
    media = upload(client, p)
    webp_project = project(client, "project-003")
    webp = upload(client, webp_project, "WEBP", "image/webp", "upload-webp")
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    path = f"/api/projects/{p['id']}/intake"
    assert client.post(path, json=body(p, media)).status_code == 401
    assert call_intake(client, p, body(p, media), OTHER).status_code == 404
    # Media belonging to another project of the same owner.
    assert (
        call_intake(client, other_project, body(other_project, media)).status_code
        == 404
    )
    missing = body(p, media, media_id="media-missing")
    assert call_intake(client, p, missing).status_code == 404
    for payload in (
        body(p, media, provider_transfer_consented=False),
        {k: v for k, v in body(p, media).items() if k != "provider_transfer_consented"},
    ):
        response = call_intake(client, p, payload)
        assert (response.status_code, response.json()["code"]) == (
            422,
            "consent_required",
        )
    stale = call_intake(
        client, p, body(p, media, expected_revision_id="inventory-stale")
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_version")
    response = call_intake(client, webp_project, body(webp_project, webp))
    assert response.status_code == 415
    # Stored oversized JPEG (directly seeded past the provider limit).
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        connection.execute(
            "UPDATE media SET body=? WHERE id=?",
            (b"\xff\xd8\xff" + b"\x00" * 5_000_000, media["id"]),
        )
    response = call_intake(client, p, body(p, media))
    assert response.status_code == 413
    assert counter["factory"] == 0 and fake.calls == []


def test_request_validation_rejects_trusted_snapshot_and_keys(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    for extra in ({"snapshot": {}}, {"provider_key": "secret"}, {"image_url": "x"}):
        response = call_intake(client, p, {**body(p, media), **extra})
        assert response.status_code == 422
        assert "secret" not in response.text
    assert counter["factory"] == 0 and fake.calls == []


@pytest.mark.parametrize(
    "value",
    [1, 0, 1.0, "true", "True", "yes", "on", "false", "1", "0", None, [], {}],
)
def test_nonboolean_consent_is_rejected_without_provider_calls(
    client, monkeypatch, value
):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final())
    counter = install(monkeypatch, fake)
    response = call_intake(client, p, body(p, media, provider_transfer_consented=value))
    assert response.status_code == 422, response.text
    assert response.json() == {
        "code": "validation_error",
        "message": "Request validation failed",
    }
    assert counter["factory"] == 0 and fake.calls == []


def test_missing_key_is_safe_503(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    response = call_intake(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (
        503,
        "provider_not_configured",
    )


@pytest.mark.parametrize(
    "response,status,code",
    [
        (GatewayError("authentication"), 502, "provider_authentication"),
        (GatewayError("access_denied"), 502, "access_denied"),
        (GatewayError("rate_limit"), 429, "rate_limit"),
        (GatewayError("timeout"), 504, "timeout"),
        (GatewayError("network_error"), 502, "network_error"),
        (GatewayError("invalid_response"), 502, "invalid_response"),
    ],
)
def test_provider_errors_are_mapped_without_leaks(
    client, monkeypatch, response, status, code
):
    p = project(client)
    media = upload(client, p)
    fake = Fake(response)
    install(monkeypatch, fake)
    result = call_intake(client, p, body(p, media))
    assert (result.status_code, result.json()["code"]) == (status, code)
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "labels,questions",
    [
        ([], []),
        (["  "], []),
        ([], [" \t\n "]),
        ([" "], ["\n"]),
    ],
)
def test_unusable_provider_output_is_redacted_502_and_readonly(
    client, monkeypatch, labels, questions
):
    p = project(client)
    media = upload(client, p)
    content = json.dumps(
        {"labels": labels, "measurement_source": "unknown", "questions": questions}
    )
    fake = Fake(final(content))
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    result = call_intake(client, p, body(p, media))
    assert result.status_code == 502, result.text
    assert result.json() == {
        "code": "invalid_response",
        "message": "Model provider returned an unusable response; retry",
    }
    assert len(fake.calls) == 1
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before
    assert client.get(f"/api/projects/{p['id']}/media", headers=AUTH).json()[
        "media"
    ] == [media]


def test_question_only_provider_output_succeeds_unknown_and_readonly(
    client, monkeypatch
):
    p = project(client)
    media = upload(client, p)
    content = json.dumps(
        {
            "labels": [],
            "measurement_source": "unknown",
            "questions": ["Measure its thickness"],
        }
    )
    fake = Fake(final(content))
    install(monkeypatch, fake)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    result = call_intake(client, p, body(p, media))
    assert result.status_code == 200, result.text
    assert result.json()["observation"] == {
        "labels": [],
        "measurement_source": "unknown",
        "questions": ["Measure its thickness"],
    }
    assert result.json()["diagnostics"]["status"] == "ok"
    assert len(fake.calls) == 1
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before


def test_malformed_provider_output_is_safe(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final("SECRET_PROVIDER_BODY not json"))
    install(monkeypatch, fake)
    result = call_intake(client, p, body(p, media))
    assert (result.status_code, result.json()["code"]) == (502, "invalid_response")
    assert "SECRET_PROVIDER_BODY" not in result.text
    assert "stand" not in result.text


def _mutate_project(tmp_path, project_id, mutate):
    with sqlite3.connect(tmp_path / "projects.sqlite3") as connection:
        row = connection.execute(
            "SELECT body FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if mutate == "delete":
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return
        data = json.loads(row[0])
        data["revision_id"] = "inventory-changed-during-call"
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(data), project_id)
        )


def test_revision_change_during_call_is_not_returned(client, monkeypatch, tmp_path):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final(), on_call=lambda: _mutate_project(tmp_path, p["id"], "change"))
    install(monkeypatch, fake)
    response = call_intake(client, p, body(p, media))
    assert (response.status_code, response.json()["code"]) == (409, "stale_version")
    assert "cardboard" not in response.text


def test_project_deletion_during_call_is_not_returned(client, monkeypatch, tmp_path):
    p = project(client)
    media = upload(client, p)
    fake = Fake(final(), on_call=lambda: _mutate_project(tmp_path, p["id"], "delete"))
    install(monkeypatch, fake)
    response = call_intake(client, p, body(p, media))
    assert response.status_code == 404
    assert "cardboard" not in response.text
