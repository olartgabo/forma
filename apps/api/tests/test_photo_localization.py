"""Real gateway with scripted transport; no paid or physical tests."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_intake_route import AUTH, OTHER, TOKENS, Fake, project, upload

from forma_api import photo_localization as runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError, MetaGateway


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client


def response(text="<0f>0<|box;x1=1;y1=2;x2=9;y2=6;w=12;h=8|>"):
    return {
        "status": "completed",
        "output": [{"content": [{"type": "output_text", "text": text}]}],
    }


def setup(client, monkeypatch, *answers, on_call=None):
    p = project(client)
    photo = upload(client, p)
    transport = Fake(*(answers or [response()]), on_call=on_call)
    gateway = MetaGateway(transport)
    monkeypatch.setattr(runtime, "default_gateway_factory", lambda: gateway)
    body = dict(
        media_id=photo["id"],
        expected_revision_id=p["revision_id"],
        idempotency_key="localization-001",
        concept="cardboard sheet",
        provider_transfer_consented=True,
    )
    return p, photo, body, transport


def call(client, p, body, auth=AUTH):
    return client.post(
        f"/api/projects/{p['id']}/photo-localizations", json=body, headers=auth
    )


def test_real_gateway_exact_replay_and_no_physical_writes(
    client, monkeypatch, tmp_path
):
    p, photo, body, fake = setup(client, monkeypatch)
    before = client.get(f"/api/projects/{p['id']}", headers=AUTH).json()
    result = call(client, p, body)
    assert result.status_code == 200, result.text
    data = result.json()
    assert result.headers["cache-control"] == "no-store"
    assert data["physical_status"] == "unverified_photo_annotation"
    assert data["boxes"][0] == dict(
        label="cardboard sheet",
        x1=1,
        y1=2,
        x2=9,
        y2=6,
        width=12,
        height=8,
        source="sam",
    )
    assert data["usage"] == dict(model_calls=1, input_tokens=None, output_tokens=None)
    assert data["width_px"] == photo["width_px"]
    assert call(client, p, body).json()["replayed"] is True
    assert len(fake.calls) == 1
    path, payload, _ = fake.calls[0]
    assert path == "/responses" and payload["model"] == "sam-3.1"
    assert payload["input"][0]["content"][1]["image_url"].startswith(
        "data:image/png;base64,"
    )
    assert client.get(f"/api/projects/{p['id']}", headers=AUTH).json() == before
    with sqlite3.connect(tmp_path / "projects.sqlite3") as c:
        for table in (
            "plans",
            "progress_events",
            "progress_evidence",
            "progress_material",
            "adapt_previews",
        ):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    "change,status",
    [
        ({"provider_transfer_consented": False}, 422),
        ({"provider_transfer_consented": "true"}, 422),
        ({"expected_revision_id": "old"}, 409),
        ({"media_id": "foreign"}, 404),
        ({"concept": "cardboard and tape"}, 422),
        ({"concept": "   "}, 422),
        ({"concept": "x" * 81}, 422),
    ],
)
def test_predispatch_guards(client, monkeypatch, change, status):
    p, _, body, fake = setup(client, monkeypatch)
    assert call(client, p, {**body, **change}).status_code == status
    assert not fake.calls


def test_scope_and_changed_body(client, monkeypatch):
    p, _, body, fake = setup(client, monkeypatch)
    assert call(client, p, body, OTHER).status_code == 404
    assert call(client, p, body, {}).status_code == 401
    other = project(client, "second-project")
    assert (
        call(
            client, other, {**body, "expected_revision_id": other["revision_id"]}
        ).status_code
        == 404
    )
    assert call(client, p, body).status_code == 200
    assert (
        call(client, p, {**body, "concept": "tape"}).json()["code"]
        == "idempotency_conflict"
    )
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "text", ["", "<0f>0<|box;x1=1;y1=2;x2=9;y2=6;w=13;h=8|>", "not boxes"]
)
def test_empty_or_malformed_and_mismatched_frame(client, monkeypatch, text):
    p, _, body, fake = setup(client, monkeypatch, response(text))
    result = call(client, p, body)
    if text == "":
        assert result.status_code == 200 and result.json()["boxes"] == []
    else:
        assert result.status_code == 502 and result.json()["code"] == "invalid_response"
    assert call(client, p, body).status_code == result.status_code
    assert len(fake.calls) == 1


def test_unknown_blocks_same_and_new_key_after_restart(client, monkeypatch, tmp_path):
    error = GatewayError("network_error", retryable=True)
    p, _, body, fake = setup(client, monkeypatch, error)
    assert call(client, p, body).json()["code"] == "generation_outcome_unknown"
    with TestClient(create_app(tmp_path, TOKENS)) as restarted:
        for key in (body["idempotency_key"], "new-key-0002"):
            assert (
                call(restarted, p, {**body, "idempotency_key": key}).json()["code"]
                == "generation_outcome_unknown"
            )
    assert len(fake.calls) == 1


def test_concurrent_pending_blocks_new_keys(client, monkeypatch):
    p, _, body, fake = setup(client, monkeypatch)

    def during():
        for key in (body["idempotency_key"], "new-key-0002"):
            result = call(client, p, {**body, "idempotency_key": key})
            assert result.json()["code"] == "generation_in_progress"

    fake.on_call = during
    assert call(client, p, body).status_code == 200
    assert len(fake.calls) == 1


def change_revision(tmp_path, p):
    with sqlite3.connect(tmp_path / "projects.sqlite3") as c:
        current = json.loads(
            c.execute("SELECT body FROM projects WHERE id=?", (p["id"],)).fetchone()[0]
        )
        current["revision_id"] = "changed-revision"
        c.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(current), p["id"])
        )


def test_stale_during_call_terminal_and_old_success_replay(
    client, monkeypatch, tmp_path
):
    p, _, body, fake = setup(client, monkeypatch)
    fake.on_call = lambda: change_revision(tmp_path, p)
    assert call(client, p, body).json()["code"] == "stale_version"
    assert call(client, p, body).json()["code"] == "stale_version"
    assert len(fake.calls) == 1


def test_success_receipt_survives_revision_change(client, monkeypatch, tmp_path):
    p, _, body, fake = setup(client, monkeypatch)
    assert call(client, p, body).status_code == 200
    change_revision(tmp_path, p)
    result = call(client, p, body).json()
    assert result["replayed"] and result["revision_id"] == body["expected_revision_id"]
    assert len(fake.calls) == 1


def test_photo_deleted_during_call_and_project_purges_receipts(
    client, monkeypatch, tmp_path
):
    p, photo, body, fake = setup(client, monkeypatch)
    fake.on_call = lambda: client.delete(
        f"/api/projects/{p['id']}/media/{photo['id']}",
        headers={**AUTH, "Idempotency-Key": "delete-photo-001"},
    )
    assert call(client, p, body).json()["code"] == "stale_version"
    result = client.delete(
        f"/api/projects/{p['id']}",
        headers={**AUTH, "Idempotency-Key": "delete-project-001"},
    )
    assert result.status_code == 200
    with sqlite3.connect(tmp_path / "projects.sqlite3") as c:
        assert (
            c.execute(
                "SELECT count(*) FROM requests WHERE scope=?",
                (p["id"] + ":photo-localization",),
            ).fetchone()[0]
            == 0
        )


def test_webp_and_oversized_photo_never_dispatch(client, monkeypatch, tmp_path):
    p, _, body, fake = setup(client, monkeypatch)
    webp = upload(client, p, "WEBP", "image/webp", "upload-webp")
    assert call(client, p, {**body, "media_id": webp["id"]}).status_code == 415
    with sqlite3.connect(tmp_path / "projects.sqlite3") as c:
        c.execute(
            "UPDATE media SET body=? WHERE id=?", (b"x" * 5_000_001, body["media_id"])
        )
    assert call(client, p, body).status_code == 413
    assert not fake.calls
