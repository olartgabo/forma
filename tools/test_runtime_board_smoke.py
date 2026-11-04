"""Offline checks for live-test accounting and dispatch boundaries."""

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_board_smoke", Path(__file__).with_name("runtime-board-smoke.py")
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class Provider:
    def __init__(self, directory, result=None, error=None):
        self.directory, self.result, self.error = directory, result, error
        self.calls = 0

    def post(self, path, payload, timeout):
        self.calls += 1
        events = [
            json.loads(line)
            for line in (self.directory / "ledger.jsonl").read_text().splitlines()
        ]
        assert events[-1]["event"] == "reserved"
        assert payload["max_completion_tokens"] == 4096
        if self.error:
            raise self.error
        return self.result


def wrapped(tmp_path, **kwargs):
    provider = Provider(tmp_path, **kwargs)
    transport = smoke.ReservedTransport(
        provider,
        tmp_path,
        {
            "max_calls": 1,
            "expires_at": (smoke.now() + timedelta(hours=1)).isoformat(),
        },
    )
    return provider, transport


def payload():
    return {"model": smoke.MODEL, "messages": [{"role": "user", "content": "test"}]}


def test_reservation_before_dispatch_usage_and_lifetime_limit(tmp_path):
    provider, transport = wrapped(
        tmp_path, result={"usage": {"prompt_tokens": 21, "completion_tokens": 7}}
    )
    transport.post("/chat/completions", payload(), 20)
    events = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == ["reserved", "settled"]
    assert events[-1]["input_tokens"] == 21
    with pytest.raises(smoke.GatewayError):
        transport.post("/chat/completions", payload(), 20)
    assert provider.calls == 1


@pytest.mark.parametrize(
    "response,error", [({}, None), (None, TimeoutError("secret raw response"))]
)
def test_unknown_halts_and_does_not_log_sensitive_exception(tmp_path, response, error):
    provider, transport = wrapped(tmp_path, result=response, error=error)
    for _ in range(2):
        with pytest.raises(smoke.GatewayError):
            transport.post("/chat/completions", payload(), 20)
    assert provider.calls == 1
    ledger = (tmp_path / "ledger.jsonl").read_text()
    assert '"event": "unknown"' in ledger
    assert "secret raw response" not in ledger


@pytest.mark.parametrize(
    "code,expected", [("timeout", "timeout"), ("secret-code", "unclassified")]
)
def test_only_allowlisted_gateway_failure_code_is_logged(tmp_path, code, expected):
    _, transport = wrapped(tmp_path, error=smoke.GatewayError(code))
    with pytest.raises(smoke.GatewayError):
        transport.post("/chat/completions", payload(), 20)
    events = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text().splitlines()
    ]
    assert events[-1]["failure_code"] == expected
    assert "secret-code" not in (tmp_path / "ledger.jsonl").read_text()


@pytest.mark.parametrize("change", ["expired", "model", "path", "oversize", "tools"])
def test_invalid_dispatch_never_contacts_provider(tmp_path, change):
    provider, transport = wrapped(tmp_path)
    data, path = payload(), "/chat/completions"
    if change == "expired":
        transport.authorization["expires_at"] = (
            smoke.now() - timedelta(seconds=1)
        ).isoformat()
    elif change == "model":
        data["model"] = "other"
    elif change == "path":
        path = "/responses"
    elif change == "tools":
        data["tools"] = [{"type": "function"}]
    else:
        data["messages"][0]["content"] = "x" * 50000
    with pytest.raises(smoke.GatewayError):
        transport.post(path, data, 20)
    assert provider.calls == 0
    assert not (tmp_path / "ledger.jsonl").exists()
