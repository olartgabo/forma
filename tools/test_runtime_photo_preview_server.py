"""Offline checks of the bounded preview provider transport."""

import json
import sys
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
import runtime_photo_preview_server as server
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from runtime_photo_preview_server import GuardedTransport, now, restrict_routes

from forma_api.model_gateway import GatewayError


class FakeTransport:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def post(self, path, payload, timeout):
        self.calls += 1
        assert payload["max_completion_tokens"] == 8192
        if self.fail:
            raise GatewayError("timeout")
        return {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}


def payload():
    return {
        "model": "muse-spark-1.3",
        "response_format": {
            "json_schema": {"schema": {"title": "ApproximateProposals"}}
        },
        "messages": [],
    }


def test_only_preview_mutations_are_allowed():
    app = FastAPI()
    calls = []

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def endpoint(path: str):
        calls.append(path)
        return {"ok": True}

    restrict_routes(app)
    with TestClient(app) as client:
        assert client.post("/api/projects").status_code == 200
        assert client.post("/api/projects/p1/media").status_code == 200
        assert client.post("/api/projects/p1/construction/propose").status_code == 200
        assert client.post("/api/projects/p1/intake/observe").status_code == 403
        assert client.post("/api/projects/p1/sourcing/research").status_code == 403
        assert client.post("/api/projects/p1/photo-localizations").status_code == 403
        assert client.put("/api/projects/p1/inventory").status_code == 403
        assert client.delete("/api/projects/p1").status_code == 403
        assert client.get("/api/health").status_code == 200
    assert len(calls) == 4


def test_finite_calls_are_reserved_and_settled(tmp_path):
    transport = FakeTransport()
    guard = GuardedTransport(transport, tmp_path, now() + timedelta(minutes=1))
    for _ in range(4):
        guard.post("/chat/completions", payload(), 10)
    with pytest.raises(GatewayError):
        guard.post("/chat/completions", payload(), 10)
    events = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert len(events) == 8 and transport.calls == 4
    assert all('"event": "reserved"' in line for line in events[::2])
    assert all('"event": "settled"' in line for line in events[1::2])


def test_unknown_halts_and_scope_or_expiry_never_dispatches(tmp_path):
    transport = FakeTransport(fail=True)
    guard = GuardedTransport(transport, tmp_path, now() + timedelta(minutes=1))
    with pytest.raises(GatewayError):
        guard.post("/wrong", payload(), 10)
    assert transport.calls == 0
    with pytest.raises(GatewayError) as failure:
        guard.post("/chat/completions", payload(), 10)
    assert failure.value.code == "network_error"
    with pytest.raises(GatewayError):
        guard.post("/chat/completions", payload(), 10)
    assert transport.calls == 1
    assert '"event": "unknown"' in (tmp_path / "ledger.jsonl").read_text()
    expired = GuardedTransport(FakeTransport(), tmp_path, now() - timedelta(seconds=1))
    with pytest.raises(GatewayError):
        expired.post("/chat/completions", payload(), 10)
    assert expired.transport.calls == 0


@pytest.mark.parametrize("fail", [False, True])
def test_main_construction_route_uses_shared_guard_and_journal(
    tmp_path, monkeypatch, fail
):
    """Exercise the real app mount: transport-only tests miss factory drift."""
    token = "offline-owner-credential-" + "x" * 32
    output = tmp_path / "run"
    monkeypatch.setenv("FORMA_RUNTIME_OWNER_TOKEN", token)
    monkeypatch.setenv("MODEL_API_KEY", "unused-offline-key")
    monkeypatch.setattr(sys, "argv", ["preview", "--output", str(output)])
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="offline-provider-key"
        ),
    )

    class AppTransport(FakeTransport):
        def post(self, path, payload, timeout):
            result = super().post(path, payload, timeout)
            assert 0 < timeout <= 60
            return result | {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"candidates": [], "questions": ["Measure the sheet."]}
                            ),
                        },
                    }
                ]
            }

    transport = AppTransport(fail=fail)
    monkeypatch.setattr(server, "MetaHTTP", lambda key: transport)

    def unguarded_factory():
        pytest.fail("The app construction route used an unguarded provider factory")

    # main must replace this exact factory, and pytest restores it afterward.
    monkeypatch.setattr(
        server.muse_construction, "default_gateway_factory", unguarded_factory
    )
    image = BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="PNG")
    auth = {"Authorization": "Bearer " + token}

    def serve(app, **kwargs):
        assert kwargs["host"] == "127.0.0.1"
        with TestClient(app) as client:
            for index in range(2 if fail else 5):
                created = client.post(
                    "/api/projects",
                    headers=auth,
                    json={
                        "goal": "An offline hypothetical desktop fixture",
                        "idempotency_key": f"project-{index:03}",
                    },
                )
                assert created.status_code == 201
                project = created.json()["project"]
                media = client.post(
                    f"/api/projects/{project['id']}/media",
                    content=image.getvalue(),
                    headers=auth
                    | {
                        "Content-Type": "image/png",
                        "Idempotency-Key": f"photo-{index:03}",
                    },
                )
                assert media.status_code == 201
                request = dict(
                    expected_revision_id=project["revision_id"],
                    idempotency_key=f"proposal-{index:03}",
                    approximate=True,
                    media_id=media.json()["media"]["id"],
                    provider_context_consented=True,
                    provider_transfer_consented=True,
                )
                if index == 0:
                    # A detailed request reaches the guard but cannot dispatch.
                    scoped = client.post(
                        f"/api/projects/{project['id']}/construction/propose",
                        headers=auth,
                        json=request | {"approximate": False},
                    )
                    assert scoped.status_code == 502
                    assert transport.calls == 0
                response = client.post(
                    f"/api/projects/{project['id']}/construction/propose",
                    headers=auth,
                    json=request,
                )
                assert response.status_code == (
                    409 if fail and index == 0 else 502 if fail or index == 4 else 200
                )
                if fail and index == 0:
                    assert response.json()["code"] == "generation_outcome_unknown"
                    assert (
                        client.post(
                            f"/api/projects/{project['id']}/construction/propose",
                            headers=auth,
                            json=request | {"idempotency_key": "another-key"},
                        ).status_code
                        == 409
                    )

    monkeypatch.setattr(server.uvicorn, "run", serve)
    server.main()
    events = [
        json.loads(line) for line in (output / "ledger.jsonl").read_text().splitlines()
    ]
    assert events[0]["event"] == "authorization"
    assert transport.calls == (1 if fail else 4)
    assert [event["event"] for event in events[1:]] == (
        ["reserved", "unknown"] if fail else ["reserved", "settled"] * 4
    )
