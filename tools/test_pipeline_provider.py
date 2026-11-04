"""Offline checks for finite live-run controls; no provider network access."""

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "pipeline_provider", Path(__file__).with_name("run-pipeline-provider.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Stub:
    def __init__(self, directory, usage=True):
        self.calls = 0
        self.directory, self.usage = directory, usage

    def post(self, path, payload, timeout):
        events = [
            json.loads(line)
            for line in (self.directory / "ledger.jsonl").read_text().splitlines()
        ]
        assert events[-1]["event"] == "reserved"
        assert payload["max_completion_tokens"] == 8192
        assert payload["reasoning_effort"] == "low"
        assert 0 < timeout <= 120
        self.calls += 1
        return (
            {"usage": {"prompt_tokens": 5, "completion_tokens": 7}}
            if self.usage
            else {}
        )


def guard(directory, *, usage=True, expired=False):
    stub = Stub(directory, usage)
    auth = dict(
        max_calls=2,
        expires_at=(
            module.now() + timedelta(seconds=-1 if expired else 1200)
        ).isoformat(),
    )
    return module.ReservedTransport(stub, directory, auth), stub


PAYLOAD = {"model": "muse-spark-1.3", "messages": []}


def test_gateway_bounds_match_supported_runtime(tmp_path):
    transport, _ = guard(tmp_path)
    gateway = module.CapturingGateway(
        transport, max_rounds=2, max_retries=0, timeout=120, budget=120
    )
    assert gateway.max_retries == 0


def test_reservation_precedes_dispatch_and_actual_usage(tmp_path):
    transport, stub = guard(tmp_path)
    transport.post("/chat/completions", PAYLOAD, 200)
    assert stub.calls == 1
    assert transport.usage[0]["actual_provider_usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
    }
    transport.post("/chat/completions", PAYLOAD, 120)
    with pytest.raises(module.GatewayError, match="runtime_run_halted"):
        transport.post("/chat/completions", PAYLOAD, 120)
    assert stub.calls == 2


def test_unknown_halts_without_retry(tmp_path):
    transport, stub = guard(tmp_path, usage=False)
    with pytest.raises(module.GatewayError, match="runtime_outcome_unknown"):
        transport.post("/chat/completions", PAYLOAD, 120)
    with pytest.raises(module.GatewayError, match="runtime_run_halted"):
        transport.post("/chat/completions", PAYLOAD, 120)
    assert stub.calls == 1
    assert (
        json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[-1])["event"]
        == "unknown"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "other"},
        {**PAYLOAD, "messages": [{"content": "x" * 48_001}]},
        {**PAYLOAD, "tools": [{"function": {"name": "write"}}]},
    ],
)
def test_invalid_inputs_never_dispatch(tmp_path, payload):
    transport, stub = guard(tmp_path)
    with pytest.raises(module.GatewayError):
        transport.post("/chat/completions", payload, 120)
    assert stub.calls == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_expired_window_never_dispatch(tmp_path):
    transport, stub = guard(tmp_path, expired=True)
    with pytest.raises(module.GatewayError, match="runtime_window_expired"):
        transport.post("/chat/completions", PAYLOAD, 120)
    assert stub.calls == 0
