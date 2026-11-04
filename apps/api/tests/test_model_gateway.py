import argparse
import importlib.util
import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from forma_api.model_gateway import (
    Box,
    GatewayError,
    ImageInput,
    MetaGateway,
    MetaHTTP,
    ProposalBudget,
    Tool,
    Trace,
)
from forma_api.provider_diagnostics import summarize_usage


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


class MetaCompatibleFake(Fake):
    """Simulates Meta Chat Completions: tool_choice supports only auto/omitted.

    Any named, required or none choice is rejected before a response is
    produced, matching the provider's HTTP 400 behaviour.
    """

    def post(self, path, payload, timeout):
        tool_choice = payload.get("tool_choice")
        if tool_choice is not None and tool_choice != "auto":
            self.calls.append((path, json.loads(json.dumps(payload)), timeout))
            raise GatewayError("provider_http_error")
        return super().post(path, payload, timeout)


def final(content='{"questions":["Measure thickness"]}', reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"content": content}}]}


def test_bounded_completion_budget_for_geometry_proposals():
    fake = Fake(final())
    MetaGateway(fake).propose("Propose panels", Proposal, max_completion_tokens=8192)
    assert fake.calls[0][1]["max_completion_tokens"] == 8192


@pytest.mark.parametrize("limit", [0, -1, 8193, True, 2048.0, "8192"])
def test_invalid_completion_budget_never_dispatches(limit):
    fake = Fake()
    with pytest.raises(ValueError, match="completion token"):
        MetaGateway(fake).propose(
            "Propose panels", Proposal, max_completion_tokens=limit
        )
    assert not fake.calls


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
    assert request["max_completion_tokens"] == 2048
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
    "unsupported",
    [
        {"type": "function", "function": {"name": "get_project_snapshot"}},
        "required",
        "none",
    ],
)
def test_meta_compatible_transport_rejects_unsupported_tool_choice(unsupported):
    fake = MetaCompatibleFake(final())
    with pytest.raises(GatewayError, match="provider_http_error"):
        fake.post(
            "/chat/completions",
            {"model": "muse-spark-1.3", "tool_choice": unsupported},
            1,
        )
    assert len(fake.calls) == 1


def test_meta_auto_first_tool_then_validated_result_then_typed_output():
    fake = MetaCompatibleFake(call("get_project_snapshot"), final())
    ran = []

    def snapshot(args):
        ran.append(args)
        return Result(needs_measurement=not args.measured)

    gateway = MetaGateway(fake)
    output = gateway.propose(
        "design",
        Proposal,
        tool=Tool("get_project_snapshot", Args, Result, snapshot),
    )
    assert output == Proposal(questions=["Measure thickness"])
    assert ran == [Args(measured=False)]
    first = fake.calls[0][1]
    assert first["tool_choice"] == "auto"
    assert first["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_project_snapshot",
                "parameters": Args.model_json_schema(),
            },
        }
    ]
    assert "get_project_snapshot" in first["messages"][0]["content"]
    assert "exactly once" in first["messages"][0]["content"]
    second = fake.calls[1][1]
    assert "tools" not in second
    assert "tool_choice" not in second
    assert (
        second["response_format"]["json_schema"]["schema"]
        == Proposal.model_json_schema()
    )
    assert second["messages"][-2]["role"] == "assistant"
    assert second["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"needs_measurement":true}',
    }
    assert [trace.status for trace in gateway.traces] == ["ok", "ok"]


@pytest.mark.parametrize(
    "response", [final(), final("Here is a design, no snapshot needed")]
)
def test_direct_final_before_tool_rejected_without_bypassing_snapshot(response):
    ran = []

    def snapshot(args):
        ran.append(args)
        return Result(needs_measurement=True)

    fake = MetaCompatibleFake(response)
    with pytest.raises(GatewayError) as error:
        MetaGateway(fake).propose(
            "design",
            Proposal,
            tool=Tool("get_project_snapshot", Args, Result, snapshot),
        )
    assert error.value.code == "invalid_tool_call"
    assert ran == []
    assert len(fake.calls) == 1


def test_multiple_tool_calls_rejected_without_execution():
    response = call("get_project_snapshot")
    response["choices"][0]["message"]["tool_calls"].append(
        response["choices"][0]["message"]["tool_calls"][0].copy()
    )
    fake = MetaCompatibleFake(response)

    def forbidden(args):
        pytest.fail("multiple tool calls executed")

    with pytest.raises(GatewayError) as error:
        MetaGateway(fake).propose(
            "design",
            Proposal,
            tool=Tool("get_project_snapshot", Args, Result, forbidden),
        )
    assert error.value.code == "invalid_tool_call"
    assert len(fake.calls) == 1


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


def _retryable(code="rate_limit", retry_after=None):
    return GatewayError(code, retryable=True, retry_after=retry_after)


def _final_with_usage():
    response = final()
    response["usage"] = {"prompt_tokens": 10, "completion_tokens": 5}
    return response


def test_retryable_rate_limit_once_then_success():
    sleeps = []
    fake = Fake(_retryable(), _final_with_usage())
    budget = ProposalBudget(max_rounds=4, seconds=60)
    gateway = MetaGateway(fake, sleep=sleeps.append)
    output = gateway.propose("test", Proposal, request_budget=budget)
    assert output.questions == ["Measure thickness"]
    assert sleeps == [1.0]
    assert [trace.status for trace in gateway.traces] == ["rate_limit", "ok"]
    assert [trace.status for trace in budget.traces] == ["rate_limit", "ok"]
    assert budget.rounds == 1
    usage = summarize_usage(budget.traces)
    assert usage.model_calls == 2
    # The failed attempt reported no usage, so totals stay unknown rather
    # than presenting the success-only 10/5 as if it were the full total.
    assert usage.input_tokens is None
    assert usage.output_tokens is None


@pytest.mark.parametrize(
    "retry_after,expected", [(None, 1.0), (2, 2.0), (10, 3.0), (0, 0.0)]
)
def test_retry_delay_uses_retry_after_capped(retry_after, expected):
    sleeps = []
    fake = Fake(_retryable(retry_after=retry_after), final())
    gateway = MetaGateway(fake, sleep=sleeps.append)
    gateway.propose("test", Proposal)
    assert sleeps == [expected]


@pytest.mark.parametrize(
    "code",
    [
        "timeout",
        "network_error",
        "invalid_response",
        "response_too_large",
        "authentication",
        "access_denied",
        "budget_exhausted",
        "round_limit",
    ],
)
def test_non_retryable_errors_never_retried(code):
    sleeps = []
    fake = Fake(GatewayError(code))
    gateway = MetaGateway(fake, sleep=sleeps.append)
    with pytest.raises(GatewayError) as error:
        gateway.propose("test", Proposal)
    assert error.value.code == code
    assert sleeps == []
    assert len(fake.calls) == 1
    assert len(gateway.traces) == 1


def test_max_retries_bounds_and_zero():
    for bad in (-1, 3):
        with pytest.raises(ValueError):
            MetaGateway(Fake(final()), max_retries=bad)
    sleeps = []
    fake = Fake(_retryable(), final())
    gateway = MetaGateway(fake, max_retries=0, sleep=sleeps.append)
    with pytest.raises(GatewayError, match="rate_limit"):
        gateway.propose("test", Proposal)
    assert len(fake.calls) == 1
    assert sleeps == []


def test_at_most_max_retries_per_call():
    sleeps = []
    fake = Fake(_retryable(), _retryable(), final())
    gateway = MetaGateway(fake, sleep=sleeps.append)  # default max_retries=1
    with pytest.raises(GatewayError, match="rate_limit"):
        gateway.propose("test", Proposal)
    assert len(fake.calls) == 2
    assert sleeps == [1.0]
    assert [t.status for t in gateway.traces] == ["rate_limit", "rate_limit"]

    sleeps2 = []
    fake2 = Fake(_retryable(), _retryable(), _final_with_usage())
    gateway2 = MetaGateway(fake2, max_retries=2, sleep=sleeps2.append)
    assert gateway2.propose("test", Proposal).questions == ["Measure thickness"]
    assert len(fake2.calls) == 3
    assert sleeps2 == [1.0, 1.0]


def test_no_sleep_when_remaining_after_wait_under_two_seconds():
    sleeps = []
    fake = Fake(_retryable(retry_after=1), final())
    gateway = MetaGateway(fake, sleep=sleeps.append)
    deadline = time.monotonic() + 2.5
    with pytest.raises(GatewayError) as error:
        gateway._post("/chat/completions", {"model": "muse-spark-1.3"}, deadline)
    assert error.value.code == "rate_limit"
    assert sleeps == []
    assert len(fake.calls) == 1


def test_summarize_usage_failed_attempt_unknown_usage_not_success_only():
    traces = [
        Trace("/chat/completions", "m", 1, "rate_limit"),
        Trace("/chat/completions", "m", 1, "provider_http_error"),
        Trace("/chat/completions", "m", 1, "ok", 10, 5),
    ]
    usage = summarize_usage(traces)
    assert usage.model_calls == 3
    # A 5xx/429 attempt with unknown usage followed by success must not
    # present known success-only totals; unknown is not zero.
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    only_failed = summarize_usage(traces[:2])
    assert only_failed.model_calls == 2
    assert only_failed.input_tokens is None
    assert only_failed.output_tokens is None


def test_summarize_usage_5xx_unknown_then_success_stays_unknown():
    traces = [
        Trace("/responses", "m", 1, "provider_http_error"),
        Trace("/responses", "m", 1, "ok", 10, 5),
    ]
    usage = summarize_usage(traces)
    assert usage.model_calls == 2
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_summarize_usage_genuine_zero_and_per_key_unknown():
    zero = summarize_usage([Trace("/chat/completions", "m", 1, "ok", 0, 0)])
    assert zero.model_calls == 1
    assert zero.input_tokens == 0
    assert zero.output_tokens == 0
    # Missing output in one attempt makes only the output aggregate unknown.
    partial = summarize_usage(
        [
            Trace("/chat/completions", "m", 1, "ok", 10, None),
            Trace("/chat/completions", "m", 1, "ok", 5, 5),
        ]
    )
    assert partial.model_calls == 2
    assert partial.input_tokens == 15
    assert partial.output_tokens is None


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (429, "rate_limit", True),
        (500, "provider_http_error", True),
        (502, "provider_http_error", True),
        (503, "provider_http_error", True),
        (504, "provider_http_error", True),
        (400, "provider_http_error", False),
        (401, "authentication", False),
        (403, "access_denied", False),
    ],
)
@pytest.mark.parametrize(
    "header,retry_after",
    [
        (None, None),
        ("2", 2.0),
        ("10", 10.0),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("-5", None),
        ("bogus", None),
        ("1.5", None),
        ("9" * 309, 3.0),
        ("9" * 5000, 3.0),
        ("0" * 5000, 0.0),
    ],
)
def test_http_retryable_marking_and_retry_after(
    monkeypatch, status, code, retryable, header, retry_after
):
    class Response:
        def __init__(self):
            self.status = status

        def getheader(self, name):
            assert name == "Retry-After"
            return header

    class Connection:
        sock = None

        def __init__(self, host, timeout):
            pass

        def connect(self):
            self.sock = _FakeSock()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", Connection
    )
    with pytest.raises(GatewayError) as error:
        MetaHTTP("secret").post("/responses", {}, 2)
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert error.value.retry_after == (retry_after if retryable else None)


@pytest.mark.parametrize("header", ["9" * 309, "9" * 5000, "0" * 5000 + "2"])
def test_http_huge_retry_after_is_safe_http_error(monkeypatch, header):
    class Response:
        status = 503

        def getheader(self, name):
            assert name == "Retry-After"
            return header

    class Connection:
        sock = None

        def __init__(self, host, timeout):
            pass

        def connect(self):
            self.sock = _FakeSock()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", Connection
    )
    with pytest.raises(GatewayError) as error:
        MetaHTTP("secret").post("/responses", {}, 2)
    # Parsing the huge header must not surface OverflowError/invalid_response.
    assert error.value.code == "provider_http_error"
    assert error.value.retryable is True
    assert error.value.retry_after == (2.0 if header.endswith("2") else 3.0)


def test_gateway_error_defaults_not_retryable():
    error = GatewayError("rate_limit")
    assert error.retryable is False
    assert error.retry_after is None


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
    fake = Fake(
        response,
        {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": ""}]}],
        },
    )
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
        sock = None

        def __init__(self, host, timeout):
            assert host == "api.meta.ai" and timeout == 2

        def connect(self):
            self.sock = _FakeSock()

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


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [{"type": "refusal", "refusal": "private"}],
        [{"type": "output_image", "data": "private"}],
    ],
)
def test_sam_missing_or_refused_output_is_not_empty_match(parts):
    response = {"status": "completed", "output": [{"content": parts}]}
    with pytest.raises(GatewayError) as error:
        MetaGateway(Fake(response)).segment(
            ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True), "sheet"
        )
    assert error.value.code in ("refusal", "invalid_segmentation")
    assert "private" not in str(error.value)


def test_absolute_timer_interrupts_stalled_headers_and_cleans_up(monkeypatch):
    interrupted = threading.Event()
    timers_before = {
        id(t) for t in threading.enumerate() if isinstance(t, threading.Timer)
    }

    class Sock:
        def shutdown(self, how):
            interrupted.set()

        def settimeout(self, value):
            pass

    class Connection:
        closed = False
        sock = Sock()

        def __init__(self, host, timeout):
            pass

        def connect(self):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            assert interrupted.wait(2), "absolute timer did not interrupt header read"
            raise OSError("private socket details")

        def close(self):
            Connection.closed = True

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", Connection
    )
    with pytest.raises(GatewayError, match="timeout"):
        MetaHTTP("secret").post("/responses", {}, 0.03)
    assert Connection.closed
    assert {
        id(t) for t in threading.enumerate() if isinstance(t, threading.Timer)
    } == timers_before


class _FakeSock:
    def __init__(self):
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class _BlockingMetaConnection:
    """Fake HTTPS connection whose DNS/connect stalls with no sock assigned.

    ``connect()`` represents both name resolution and TCP/TLS connect,
    which ``http.client`` performs inside ``connect()`` before ``sock``
    exists.
    """

    instances = []

    def __init__(self, host, timeout=None, **kwargs):
        assert host == "api.meta.ai"
        self.host = host
        self.timeout = timeout
        self.sock = None
        self.closed = False
        self.request_calls = []
        self.connect_calls = 0
        self.connect_started = threading.Event()
        self.release_connect = threading.Event()
        _BlockingMetaConnection.instances.append(self)

    def connect(self):
        self.connect_calls += 1
        self.connect_started.set()
        # Bounded so a failing test cannot hang the suite forever.
        self.release_connect.wait(timeout=10)
        self.sock = _FakeSock()

    def request(self, method, url, body=None, headers=None):
        self.request_calls.append((method, url, body, headers))

    def getresponse(self):  # pragma: no cover - must never be reached
        raise AssertionError("getresponse must not be called after timeout")

    def close(self):
        self.closed = True
        if self.sock is not None:
            self.sock.close()


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_http_stalled_connect_no_sock_times_out_and_never_dispatches(monkeypatch):
    _BlockingMetaConnection.instances = []
    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection",
        _BlockingMetaConnection,
    )
    start = time.monotonic()
    with pytest.raises(GatewayError, match="timeout") as error:
        MetaHTTP("secret").post("/chat/completions", {"prompt": "private"}, 0.3)
    elapsed = time.monotonic() - start
    assert error.value.code == "timeout"
    assert "secret" not in str(error.value)
    # Caller returns near its deadline (plus at most the documented grace)
    # even though connect is still blocked and no socket was ever assigned.
    assert elapsed < 1.5
    assert len(_BlockingMetaConnection.instances) == 1
    conn = _BlockingMetaConnection.instances[0]
    assert conn.connect_started.is_set()
    assert conn.sock is None
    assert conn.connect_calls == 1
    assert conn.request_calls == []

    # Releasing the blocked stage afterwards must not dispatch the POST
    # (no method, path, body or Authorization header) and must clean up.
    conn.release_connect.set()
    assert _wait_until(lambda: conn.closed)
    assert conn.request_calls == []
    assert conn.connect_calls == 1  # no implicit reconnect / automatic retry
    assert conn.sock is not None and conn.sock.closed


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 121, "1", None])
def test_http_invalid_timeout_rejected_before_connection(monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("connection must not be created for an invalid timeout")

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", forbidden
    )
    with pytest.raises(GatewayError, match="invalid_timeout"):
        MetaHTTP("secret").post("/responses", {}, timeout)


def test_http_invalid_endpoint_rejected_before_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("connection must not be created for an invalid endpoint")

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", forbidden
    )
    with pytest.raises(GatewayError, match="invalid_endpoint"):
        MetaHTTP("secret").post("/admin", {}, 1)


def test_http_success_path_dispatches_once_after_connect(monkeypatch):
    class Response:
        status = 200

        def __init__(self):
            self._chunks = iter([b'{"ok":', b"true}", b""])

        def read1(self, size):
            return next(self._chunks)

    class Connection:
        closed = False
        sock = None

        def __init__(self, host, timeout):
            assert host == "api.meta.ai" and timeout == 2
            self.calls = []

        def connect(self):
            self.sock = _FakeSock()

        def request(self, method, path, **kwargs):
            # http.client only auto-connects when sock is None; the explicit
            # connect above must have assigned it before any dispatch.
            assert self.sock is not None
            self.calls.append((method, path, kwargs))

        def getresponse(self):
            return Response()

        def close(self):
            Connection.closed = True

    instances = []

    def factory(host, timeout):
        conn = Connection(host, timeout)
        instances.append(conn)
        return conn

    monkeypatch.setattr("forma_api.model_gateway.http.client.HTTPSConnection", factory)
    result = MetaHTTP("secret").post("/responses", {"x": 1}, 2)
    assert result == {"ok": True}
    assert Connection.closed
    assert len(instances) == 1
    method, path, kwargs = instances[0].calls[0]
    assert (method, path) == ("POST", "/v1/responses")
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert json.loads(kwargs["body"]) == {"x": 1}


def test_http_trickling_response_hits_total_deadline(monkeypatch):
    class Response:
        status = 200

        def read1(self, size):
            time.sleep(0.05)
            return b"x"

    class Connection:
        closed = False
        sock = None

        def __init__(self, host, timeout):
            pass

        def connect(self):
            self.sock = _FakeSock()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            Connection.closed = True

    monkeypatch.setattr(
        "forma_api.model_gateway.http.client.HTTPSConnection", Connection
    )
    start = time.monotonic()
    with pytest.raises(GatewayError, match="timeout"):
        MetaHTTP("secret").post("/responses", {}, 0.22)
    elapsed = time.monotonic() - start
    # Bytes keep arriving, so an inactivity timeout would never fire; the
    # total deadline (plus at most the cleanup grace) must cut it off.
    assert elapsed < 1.5
    assert Connection.closed


SMOKE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "smoke_meta.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_meta", SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


smoke_meta = _load_smoke()


def test_smoke_preflight_lists_all_blockers_without_network(monkeypatch):
    def _forbid(*args, **kwargs):
        pytest.fail("preflight must not touch the network")

    monkeypatch.setattr(
        smoke_meta.MetaGateway,
        "from_env",
        classmethod(lambda cls: _forbid()),
    )
    monkeypatch.setattr("forma_api.model_gateway.MetaHTTP.post", _forbid)
    args = argparse.Namespace(
        image=Path("/nonexistent/team-photo.jpg"),
        consented=False,
        live=False,
    )
    blockers = smoke_meta.preflight(args, {})
    assert blockers == [
        "MODEL_API_KEY missing",
        "real team photo missing",
        "photo consent missing",
        "explicit --live missing; no network attempted",
    ]


def test_smoke_success_reports_metadata_without_private_data(monkeypatch):
    fake_key = "FAKE_KEY_ABC123"
    secret_label = "SECRET_LABEL_XYZ"
    secret_question = "SECRET_QUESTION_XYZ"
    tool_response = call("check_measurements", '{"measurements_confirmed":false}')
    final_response = final(
        json.dumps(
            {
                "labels": [secret_label],
                "measurement_source": "unknown",
                "questions": [secret_question],
            }
        )
    )
    sam_response = {
        "status": "completed",
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": "<0f>0<|box;x1=1;y1=2;x2=20;y2=30;w=40;h=50|>",
                    }
                ]
            }
        ],
    }
    fake = Fake(tool_response, final_response, sam_response)
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    transport = MetaHTTP(fake_key)
    transport.post = fake.post
    gateway = MetaGateway(transport)
    image = ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True)
    exit_code, report = smoke_meta.run_smoke(gateway, image, "cardboard sheet")
    assert exit_code == 0
    assert report["status"] == "ok"
    assert report["spark_image_schema_tool"] == "validated"
    assert report["label_count"] == 1
    assert report["question_count"] == 1
    assert report["box_count"] == 1
    assert report["sam"] == "boxes_returned"
    assert report["models"] == {"spark": gateway.spark, "sam": gateway.sam}
    assert report["models"] == {"spark": "muse-spark-1.3", "sam": "sam-3.1"}
    expected_python = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    assert report["runtime"]["python"] == expected_python
    assert isinstance(report["runtime"]["pydantic"], str)
    assert report["runtime"]["forma_api"] is None or isinstance(
        report["runtime"]["forma_api"], str
    )
    assert report["runtime"]["http_client"] == "stdlib http.client"
    assert [t["endpoint"] for t in report["traces"]] == [
        "/chat/completions",
        "/chat/completions",
        "/responses",
    ]
    assert [t["status"] for t in report["traces"]] == ["ok", "ok", "ok"]
    assert set(report) == {
        "prompt_version",
        "schema_version",
        "runtime",
        "models",
        "status",
        "spark_image_schema_tool",
        "label_count",
        "question_count",
        "sam",
        "box_count",
        "traces",
    }
    assert "boxes" not in report
    serialized = json.dumps(report)
    assert fake_key not in serialized
    assert secret_label not in serialized
    assert secret_question not in serialized
    assert "data:image" not in serialized
    assert '"x1"' not in serialized
    assert '"x2"' not in serialized
    assert '"y1"' not in serialized
    assert '"y2"' not in serialized


def test_smoke_spark_error_skips_sam():
    fake = Fake(GatewayError("authentication"))
    gateway = MetaGateway(fake)
    image = ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True)
    exit_code, report = smoke_meta.run_smoke(gateway, image, "cardboard sheet")
    assert exit_code == 1
    assert report["status"] == "authentication"
    assert "sam" not in report
    assert len(report["traces"]) == 1
    assert report["traces"][0]["endpoint"] == "/chat/completions"
    assert report["traces"][0]["status"] == "authentication"


def test_smoke_sam_refusal_fails_with_sam_failed():
    tool_response = call("check_measurements", '{"measurements_confirmed":false}')
    final_response = final(
        json.dumps(
            {
                "labels": ["plain sheet"],
                "measurement_source": "unknown",
                "questions": ["What is the thickness?"],
            }
        )
    )
    sam_refusal = {
        "status": "completed",
        "output": [{"content": [{"type": "refusal", "refusal": "no"}]}],
    }
    fake = Fake(tool_response, final_response, sam_refusal)
    gateway = MetaGateway(fake)
    image = ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True)
    exit_code, report = smoke_meta.run_smoke(gateway, image, "cardboard sheet")
    assert exit_code == 3
    assert report["status"] == "sam_failed"
    assert report["spark_image_schema_tool"] == "validated"
    assert report["sam"] == "refusal"
    assert report["fallback"] == (
        "manual Box validation available; user must label/correct"
    )


def test_smoke_sam_empty_output_reports_ok_no_matches():
    tool_response = call("check_measurements", '{"measurements_confirmed":false}')
    final_response = final(
        json.dumps(
            {
                "labels": ["plain sheet"],
                "measurement_source": "unknown",
                "questions": ["What is the thickness?"],
            }
        )
    )
    sam_empty = {
        "status": "completed",
        "output": [{"content": [{"type": "output_text", "text": ""}]}],
    }
    fake = Fake(tool_response, final_response, sam_empty)
    gateway = MetaGateway(fake)
    image = ImageInput(b"\xff\xd8\xffsynthetic", "image/jpeg", True)
    exit_code, report = smoke_meta.run_smoke(gateway, image, "cardboard sheet")
    assert exit_code == 0
    assert report["status"] == "ok"
    assert report["sam"] == "no_matches_manual_box_required"
    assert report["box_count"] == 0


def test_smoke_main_oversized_photo_reports_invalid_image(
    monkeypatch, tmp_path, capsys
):
    fake_key = "FAKE_KEY_OVERSIZED_456"
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    photo = tmp_path / "team-photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff" + b"\x00" * 5_000_000)
    fake = Fake()
    monkeypatch.setattr(
        smoke_meta.MetaGateway,
        "from_env",
        classmethod(lambda cls: MetaGateway(fake)),
    )
    exit_code = smoke_meta.main(["--live", "--consented", "--image", str(photo)])
    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "invalid_image"
    assert fake.calls == []
    assert fake_key not in json.dumps(output)


def test_smoke_main_png_named_jpg_uses_sniffed_mime(monkeypatch, tmp_path, capsys):
    fake_key = "FAKE_KEY_PNG_MIME_789"
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    photo = tmp_path / "team-photo.jpg"
    photo.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    tool_response = call("check_measurements", '{"measurements_confirmed":false}')
    final_response = final(
        json.dumps(
            {
                "labels": ["plain sheet"],
                "measurement_source": "unknown",
                "questions": ["What is the thickness?"],
            }
        )
    )
    sam_empty = {
        "status": "completed",
        "output": [{"content": [{"type": "output_text", "text": ""}]}],
    }
    fake = Fake(tool_response, final_response, sam_empty)
    monkeypatch.setattr(
        smoke_meta.MetaGateway,
        "from_env",
        classmethod(lambda cls: MetaGateway(fake)),
    )
    exit_code = smoke_meta.main(["--live", "--consented", "--image", str(photo)])
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert photo.suffix == ".jpg"
    url = fake.calls[0][1]["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert fake_key not in json.dumps(output)


def test_smoke_main_unsupported_format_reports_invalid_image(
    monkeypatch, tmp_path, capsys
):
    fake_key = "FAKE_KEY_WEBP_INVALID_321"
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    photo = tmp_path / "team-photo.jpg"
    photo.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 synthetic")
    fake = Fake()
    monkeypatch.setattr(
        smoke_meta.MetaGateway,
        "from_env",
        classmethod(lambda cls: MetaGateway(fake)),
    )
    exit_code = smoke_meta.main(["--live", "--consented", "--image", str(photo)])
    assert exit_code == 1
    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["status"] == "invalid_image"
    assert fake.calls == []
    assert "traces" in output
    assert fake_key not in raw
    assert "RIFF" not in raw
    assert "WEBP" not in raw


def test_smoke_main_empty_photo_reports_invalid_image(monkeypatch, tmp_path, capsys):
    fake_key = "FAKE_KEY_EMPTY_INVALID_654"
    monkeypatch.setenv("MODEL_API_KEY", fake_key)
    photo = tmp_path / "team-photo.jpg"
    photo.write_bytes(b"")
    fake = Fake()
    monkeypatch.setattr(
        smoke_meta.MetaGateway,
        "from_env",
        classmethod(lambda cls: MetaGateway(fake)),
    )
    exit_code = smoke_meta.main(["--live", "--consented", "--image", str(photo)])
    assert exit_code == 1
    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["status"] == "invalid_image"
    assert "traces" in output
    assert fake.calls == []
    assert fake_key not in raw


def test_extended_gateway_timeout_respects_shared_budget():
    fake = Fake(final())
    gateway = MetaGateway(fake, timeout=120, budget=120)
    gateway.propose("Question", Proposal)
    assert 119 < fake.calls[0][2] <= 120
    with pytest.raises(ValueError, match="gateway bounds"):
        MetaGateway(fake, timeout=121)
    ordinary = MetaGateway(fake)
    assert ordinary.timeout == 20
    assert ordinary.budget == 60


def test_http_accepts_extended_timeout_without_real_network(monkeypatch):
    observed = []

    def post_once(self, path, body, timeout, expired, shared):
        observed.append(timeout)
        return {"ok": True}

    monkeypatch.setattr(MetaHTTP, "_post_once", post_once)
    assert MetaHTTP("secret").post("/chat/completions", {}, 120) == {"ok": True}
    assert observed == [120]


def test_validation_diagnostics_bound_paths_and_redact_unknown_properties():
    fake = Fake(
        final(json.dumps({"questions": ["ok"], "PRIVATE-key": "PRIVATE-value"}))
    )
    with pytest.raises(GatewayError) as failure:
        MetaGateway(fake).propose("private prompt", Proposal)
    assert failure.value.diagnostic_reason == "invalid_schema"
    assert failure.value.validation_issues == [
        {"path": ["<field>"], "type": "extra_forbidden"}
    ]
    assert "PRIVATE" not in json.dumps(failure.value.validation_issues)
    fake = Fake(final(json.dumps({"questions": ["ok"] * 25 + [None] * 30})))
    with pytest.raises(GatewayError) as failure:
        MetaGateway(fake).propose("private prompt", Proposal)
    issues = failure.value.validation_issues
    assert len(issues) == 16
    assert all(
        issue == {"path": ["questions", "<index>"], "type": "string_type"}
        for issue in issues
    )


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high", "xhigh", "max"])
def test_explicit_reasoning_effort_is_forwarded(effort):
    fake = Fake(final())
    MetaGateway(fake).propose("Propose panels", Proposal, reasoning_effort=effort)
    assert fake.calls[0][1]["reasoning_effort"] == effort


@pytest.mark.parametrize("effort", ["none", "auto", "LOW", "", True, 1, [], {}])
def test_invalid_reasoning_effort_rejected_before_dispatch(effort):
    fake = Fake()
    with pytest.raises(ValueError, match="reasoning effort"):
        MetaGateway(fake).propose("Propose panels", Proposal, reasoning_effort=effort)
    assert not fake.calls
