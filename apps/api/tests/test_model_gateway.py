import json
from dataclasses import asdict

import pytest
from pydantic import BaseModel, ConfigDict

from forma_api.model_gateway import (
    Box,
    GatewayError,
    ImageInput,
    MetaGateway,
    MetaHTTP,
    Tool,
)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    questions: list[str]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    measured: bool


class Result(BaseModel):
    needs_measurement: bool


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def final(content='{"questions":["Measure thickness"]}', reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"content": content}}]}


def call(name="check_measurements", arguments='{"measured":false}'):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ]
                },
            }
        ]
    }


def test_image_structured_proposal_and_safe_trace():
    fake = Fake(final())
    gateway = MetaGateway(fake)
    output = gateway.propose(
        "private goal",
        Proposal,
        image=ImageInput(b"\x89PNG\r\n\x1a\nsynthetic", "image/png", True),
    )
    assert output.questions == ["Measure thickness"]
    request = fake.calls[0][1]
    assert (
        request["response_format"]["json_schema"]["schema"]
        == Proposal.model_json_schema()
    )
    assert request["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;"
    )
    assert "private" not in json.dumps([asdict(t) for t in gateway.traces])


def test_validated_deterministic_tool_roundtrip():
    fake = Fake(call(), final())
    ran = []

    def check(args):
        ran.append(args)
        return Result(needs_measurement=not args.measured)

    gateway = MetaGateway(fake)
    gateway.propose(
        "inventory", Proposal, tool=Tool("check_measurements", Args, Result, check)
    )
    assert ran == [Args(measured=False)]
    messages = fake.calls[1][1]["messages"]
    assert messages[-2]["role"] == "assistant"
    assert messages[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"needs_measurement":true}',
    }
    assert "tools" not in fake.calls[1][1]


@pytest.mark.parametrize(
    "response",
    [
        call("commit_plan"),
        call(arguments='{"measured":"yes"}'),
        call(arguments='{"measured":false,"extra":1}'),
        final(),
        final("not json"),
        {"choices": []},
    ],
)
def test_invalid_tool_never_executes(response):
    fake = Fake(response)

    def forbidden(args):
        pytest.fail("invalid tool executed")

    with pytest.raises(GatewayError):
        MetaGateway(fake).propose(
            "test", Proposal, tool=Tool("check_measurements", Args, Result, forbidden)
        )
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        final("not json"),
        final('{"questions":[],"extra":1}'),
        final(reason="length"),
        {"choices": [{"message": {"refusal": "private reason"}}]},
    ],
)
def test_bad_output_is_safe(response):
    with pytest.raises(GatewayError) as error:
        MetaGateway(Fake(response)).propose("private", Proposal)
    assert "private" not in str(error.value)


def test_round_cap_and_no_hidden_retry():
    fake = Fake(call())
    with pytest.raises(GatewayError, match="round_limit"):
        MetaGateway(fake, max_rounds=1).propose(
            "test",
            Proposal,
            tool=Tool(
                "check_measurements",
                Args,
                Result,
                lambda args: Result(needs_measurement=True),
            ),
        )
    assert len(fake.calls) == 1
    failed = Fake(GatewayError("rate_limit"))
    with pytest.raises(GatewayError, match="rate_limit"):
        MetaGateway(failed).propose("test", Proposal)
    assert len(failed.calls) == 1


def test_manual_boxes_offline_and_bounds():
    assert (
        Box(label="sheet", x1=0, y1=0, x2=99, y2=49, width=100, height=50).source
        == "manual"
    )
    with pytest.raises(ValueError):
        Box(label="sheet", x1=0, y1=0, x2=100, y2=49, width=100, height=50)


def test_sam_boxes_and_empty_match():
    image = ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True)
    response = {
        "status": "completed",
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": "<0f>0<|box;x1=1;y1=2;x2=20;y2=30;w=40;h=50|><|mask;x=0;y=0;data=~...|>",
                    }
                ]
            }
        ],
    }
    fake = Fake(response, {"status": "completed", "output": []})
    gateway = MetaGateway(fake)
    assert gateway.segment(image, "cardboard sheet")[0].source == "sam"
    assert gateway.segment(image, "cardboard sheet") == []
    assert fake.calls[0][0] == "/responses"
    assert fake.calls[0][1]["stream"] is False


def test_consent_and_concept_rejected_before_network():
    fake = Fake()
    with pytest.raises(GatewayError, match="image_consent_required"):
        MetaGateway(fake).propose(
            "test", Proposal, image=ImageInput(b"private", "image/png")
        )
    with pytest.raises(GatewayError, match="single_concept_required"):
        MetaGateway(fake).segment(ImageInput(b"private", "image/png"), "sheet and tape")
    assert not fake.calls


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "access_denied"),
        (429, "rate_limit"),
        (302, "provider_http_error"),
        (500, "provider_http_error"),
    ],
)
def test_http_errors_closed_and_redacted(monkeypatch, status, code):
    class Connection:
        closed = False

        def __init__(self, host, timeout):
            assert host == "api.meta.ai" and timeout == 2

        def request(self, method, path, **kwargs):
            assert method == "POST" and path == "/v1/responses"
            assert kwargs["headers"]["Authorization"] == "Bearer secret"

        def getresponse(self):
            return type("Response", (), {"status": status})()

        def close(self):
            Connection.closed = True

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", Connection
    )
    with pytest.raises(GatewayError, match=code) as error:
        MetaHTTP("secret").post("/responses", {}, 2)
    assert "secret" not in str(error.value)
    assert Connection.closed


def test_tool_failure_does_not_leak_private_exception():
    def broken(args):
        raise RuntimeError("private secret")

    with pytest.raises(GatewayError, match="tool_failed") as error:
        MetaGateway(Fake(call())).propose(
            "test", Proposal, tool=Tool("check_measurements", Args, Result, broken)
        )
    assert "private" not in str(error.value)


def test_budget_exhaustion_stops_before_next_model_round(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("forma_api.model_gateway.time.monotonic", lambda: clock[0])
    fake = Fake(call())

    def slow_tool(args):
        clock[0] = 61.0
        return Result(needs_measurement=True)

    with pytest.raises(GatewayError, match="budget_exhausted"):
        MetaGateway(fake).propose(
            "test", Proposal, tool=Tool("check_measurements", Args, Result, slow_tool)
        )
    assert len(fake.calls) == 1
    assert 0 < fake.calls[0][2] <= 20


@pytest.mark.parametrize("response", [[], {"choices": [{"message": None}]}])
def test_malformed_transport_shape_has_safe_failure(response):
    with pytest.raises(GatewayError):
        MetaGateway(Fake(response)).propose("test", Proposal)
