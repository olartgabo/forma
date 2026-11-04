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
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["project_id"] == p["id"]
    assert result["revision_id"] == p["revision_id"]
    assert result["media_id"] == media["id"]
    assert result["observation"] == {
        "labels": ["cardboard sheet"],
        "measurement_source": "unknown",
        "questions": ["Measure thickness"],
        "items": [],
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
    assert {k: result.json()[k] for k in ("code", "message")} == {
        "code": "invalid_response",
        "message": "Model provider returned an unusable response; retry",
    }
    assert result.json()["diagnostics"]["reason"] == "empty_observation"
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
        "items": [],
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


def test_private_errors_are_not_cached(client, monkeypatch):
    p = project(client)
    media = upload(client, p)
    install(monkeypatch, Fake(GatewayError("authentication")))
    for payload in (
        {},
        body(p, media, provider_transfer_consented=False),
        body(p, media),
    ):
        response = call_intake(client, p, payload)
        assert response.status_code in (422, 502)
        assert response.headers["cache-control"] == "no-store"


def test_catalog_items_are_returned_and_off_catalog_answers_refused(
    client, monkeypatch
):
    p = project(client)
    media = upload(client, p)
    items = [
        {
            "identity": {
                "outcome": "catalog",
                "category_id": "cardstock",
                "alternatives": ["thin_packaging_card"],
            },
            "visible_evidence": "thin printed card",
            "box": {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.6},
            "visibility": "partial",
            "instance": "single",
        },
        {
            "identity": {"outcome": "uncertain", "alternatives": []},
            "visible_evidence": "grey shape under the box",
            "box": None,
            "visibility": "unclear",
            "instance": "group_count_unknown",
        },
    ]
    content = json.dumps(
        {"labels": [], "measurement_source": "unknown", "questions": [], "items": items}
    )
    fake = Fake(final(content))
    install(monkeypatch, fake)
    result = call_intake(client, p, body(p, media))
    assert result.status_code == 200, result.text
    returned = result.json()["observation"]["items"]
    assert [i["identity"]["outcome"] for i in returned] == ["catalog", "uncertain"]
    assert "category_id" not in returned[1]["identity"] or (
        returned[1]["identity"]["category_id"] is None
    )
    # The catalog and its rules are in the trusted instructions sent.
    sent = json.dumps(fake.calls[0])
    assert "corrugated_cardboard" in sent and "outcome=uncertain" in sent

    q = project(client, key="project-002")
    media = upload(client, q)
    forced = [{**items[0], "identity": {"outcome": "catalog", "category_id": "pet"}}]
    content = json.dumps(
        {
            "labels": ["x"],
            "measurement_source": "unknown",
            "questions": [],
            "items": forced,
        }
    )
    install(monkeypatch, Fake(final(content)))
    refused = call_intake(client, q, body(q, media))
    assert refused.status_code == 502
    assert refused.json()["code"] == "invalid_response"


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("refusal", "refusal"),
        ("length", "incomplete_output"),
        ("schema", "invalid_schema"),
        ("json", "invalid_json"),
        ("shape", "invalid_proposal"),
        ("timeout", "timeout"),
    ],
)
def test_owner_receives_safe_failure_diagnostics(client, monkeypatch, kind, reason):
    p = project(client)
    media = upload(client, p)
    response = final()
    response["usage"] = {"prompt_tokens": 31, "completion_tokens": 2048}
    if kind == "refusal":
        response["choices"][0]["message"]["refusal"] = "PRIVATE refusal text"
    elif kind == "length":
        response["choices"][0]["finish_reason"] = "length"
    elif kind == "schema":
        response["choices"][0]["message"]["content"] = '{"private":"PRIVATE payload"}'
    elif kind == "json":
        response["choices"][0]["message"]["content"] = "PRIVATE invalid JSON"
    elif kind == "shape":
        response["choices"] = []
    else:
        response = GatewayError("timeout")
    fake = Fake(response)
    install(monkeypatch, fake)
    result = call_intake(client, p, body(p, media))
    assert result.status_code == (504 if kind == "timeout" else 502)
    assert result.headers["Cache-Control"] == "no-store"
    diagnostics = result.json()["diagnostics"]
    assert diagnostics["reason"] == reason
    assert diagnostics["model"] == "muse-spark-1.3"
    assert diagnostics["elapsed_ms"] >= 0
    assert diagnostics["usage"]["model_calls"] == 1
    if kind == "timeout":
        assert diagnostics["usage"].get("input_tokens") is None
        assert diagnostics["usage"].get("output_tokens") is None
    else:
        assert diagnostics["usage"] == {
            "model_calls": 1,
            "input_tokens": 31,
            "output_tokens": 2048,
        }
    if kind == "schema":
        assert {"path": ["<field>"], "type": "extra_forbidden"} in diagnostics[
            "validation_issues"
        ]
    elif kind == "json":
        assert diagnostics["validation_issues"] == [
            {"path": [], "type": "json_invalid"}
        ]
    assert "PRIVATE" not in result.text
    assert len(fake.calls) == 1
    assert fake.calls[0][1]["max_completion_tokens"] == 8192
    denied = client.post(
        f"/api/projects/{p['id']}/intake", headers=OTHER, json=body(p, media)
    )
    assert denied.status_code == 404
    assert "diagnostics" not in denied.json()
    assert len(fake.calls) == 1
