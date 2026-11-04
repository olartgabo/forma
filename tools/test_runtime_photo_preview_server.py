"""Offline checks of the bounded preview provider transport."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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
