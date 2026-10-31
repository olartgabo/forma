import argparse
import importlib.util
import json
import sys
import threading
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

    class Connection:
        closed = False
        sock = Sock()

        def __init__(self, host, timeout):
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
