"""Offline contract tests for Meta intake research roles."""

import json
import time

import pytest

from forma_api.intake_research_muse import ResearchOption, adjudicate, analyze, scout
from forma_api.model_gateway import GatewayError, MetaGateway

BRIEF = "Find a tabletop stand approach using sheet stock and tape."
CLAIM = "A taped hinge can join the rear brace to the base."
URL = "https://www.instructables.com/example-stand/"


class Transport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, payload, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def message(text, annotations=()):
    return {
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": list(annotations),
            }
        ],
    }


def response(*items):
    return {"status": "completed", "output": list(items)}


def search_call():
    return {"type": "web_search_call", "status": "completed"}


def citation(**changes):
    return {
        "type": "url_citation",
        "title": "  Cardboard  tabletop stand ",
        "url": URL,
        "start_index": 0,
        "end_index": len(CLAIM),
        **changes,
    }


def test_scout_only_keeps_provider_cited_spans_after_search():
    transport = Transport(
        response(
            {"type": "reasoning", "summary": "Provider reasoning stays private."},
            search_call(),
            message(
                CLAIM + " This is an uncited claim.",
                (citation(), citation(), citation(end_index=1000)),
            ),
        )
    )
    gateway = MetaGateway(transport, max_retries=2)
    findings = scout(gateway, BRIEF, time.monotonic() + 2)
    assert [finding.model_dump() for finding in findings] == [
        {"claim": CLAIM, "title": "Cardboard tabletop stand", "url": URL}
    ]
    ((path, payload, timeout),) = transport.calls
    assert path == "/responses"
    assert payload["input"] == BRIEF
    assert payload["store"] is False
    assert payload["max_tool_calls"] == 1
    assert payload["max_output_tokens"] > 0
    assert payload["tools"] == [{"type": "web_search"}]
    assert 0 < timeout <= 2
    assert len(gateway.traces) == 1


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://www.instructables.com/test",
        "https://www.instructables.com@localhost/test",
        "https://www.instructables.com:8080/test",
        "https://192.168.0.1/test",
        "https://[::1]/test",
        "https://0x7f000001/test",
        "https://lab.home.arpa/test",
        "https://x.internal/test",
        "https://foo.localhost/test",
        "https://www.instructables.com\\@localhost/test",
    ],
)
def test_scout_drops_nonpublic_or_ambiguous_urls(url):
    transport = Transport(response(search_call(), message(CLAIM, (citation(url=url),))))
    assert scout(MetaGateway(transport), BRIEF, time.monotonic() + 2) == ()


def test_scout_requires_search_and_annotation_and_rejects_duplicated_tool_calls():
    deadline = time.monotonic() + 2
    fake_claim = message(CLAIM, (citation(),))
    skipped = MetaGateway(Transport(response(fake_claim)))
    assert scout(skipped, BRIEF, deadline) == ()
    uncited = MetaGateway(Transport(response(search_call(), message(CLAIM))))
    assert scout(uncited, BRIEF, deadline) == ()
    extra_calls = MetaGateway(
        Transport(response(search_call(), search_call(), fake_claim))
    )
    with pytest.raises(GatewayError, match="invalid_response"):
        scout(extra_calls, BRIEF, deadline)


def test_no_retry_and_no_dispatch_after_deadline():
    transport = Transport(GatewayError("rate_limit", retryable=True))
    gateway = MetaGateway(transport, max_retries=2)
    with pytest.raises(GatewayError, match="rate_limit"):
        scout(gateway, BRIEF, time.monotonic() + 5)
    with pytest.raises(GatewayError, match="budget_exhausted"):
        scout(gateway, BRIEF, time.monotonic() - 1)
    assert len(transport.calls) == 1


def test_valid_response_arriving_after_deadline_is_discarded(monkeypatch):
    clock = [10.0]

    class LateTransport(Transport):
        def post(self, path, payload, timeout):
            assert timeout == 1
            clock[0] = 11.1
            return super().post(path, payload, timeout)

    transport = LateTransport(response(search_call(), message(CLAIM, (citation(),))))
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    gateway = MetaGateway(transport)
    with pytest.raises(GatewayError, match="budget_exhausted"):
        scout(gateway, BRIEF, deadline=11.0)
    assert len(transport.calls) == 1


def test_contributor_mode_refused_before_dispatch():
    transport = Transport(response())
    with pytest.raises(GatewayError, match="access_denied"):
        scout(
            MetaGateway(transport, spark="muse-spark-1.3-contributor"),
            BRIEF,
            time.monotonic() + 2,
        )
    assert not transport.calls


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_nonterminal_provider_response_has_unknown_outcome(status):
    gateway = MetaGateway(Transport({"status": status, "output": []}))
    with pytest.raises(GatewayError, match="timeout"):
        scout(gateway, BRIEF, time.monotonic() + 2)


def test_analyst_receives_public_brief_only_and_cannot_invent_check_families():
    transport = Transport(response(message('{"focus":"stock"}')))
    assert analyze(MetaGateway(transport), BRIEF, time.monotonic() + 2).focus == "stock"
    payload = transport.calls[0][1]
    assert payload["store"] is False
    assert json.loads(payload["input"]) == {"public_brief": BRIEF}
    assert "tools" not in payload
    assert payload["text"]["format"]["type"] == "json_schema"
    invalid = Transport(response(message('{"focus":"load_capacity"}')))
    with pytest.raises(GatewayError, match="invalid_response"):
        analyze(MetaGateway(invalid), BRIEF, time.monotonic() + 2)


@pytest.mark.parametrize(
    ("provider_output", "selected"),
    [
        ('{"option_id":"second"}', "second"),
        ('{"option_id":"no_preference"}', "no_preference"),
        ('{"option_id":"invented"}', None),
        ('{"option_id":"first","physical_pass":true}', None),
    ],
)
def test_adjudicator_cannot_select_outside_engine_option_aliases(
    provider_output, selected
):
    deadline = time.monotonic() + 2
    analysis = analyze(
        MetaGateway(Transport(response(message('{"focus":"stock"}')))), BRIEF, deadline
    )
    findings = scout(
        MetaGateway(Transport(response(search_call(), message(CLAIM, (citation(),))))),
        BRIEF,
        deadline,
    )
    options = (
        ResearchOption(id="first", tradeoff="least_stock"),
        ResearchOption(
            id="second",
            tradeoff="alternative_stock_or_base",
            different_base_depth=True,
            uses_less_tape=True,
        ),
    )
    transport = Transport(response(message(provider_output)))
    gateway = MetaGateway(transport)
    if selected is not None:
        assert (
            adjudicate(gateway, BRIEF, findings, analysis, options, deadline)
            == selected
        )
    else:
        with pytest.raises(GatewayError, match="invalid_response"):
            adjudicate(gateway, BRIEF, findings, analysis, options, deadline)
    payload = transport.calls[0][1]
    assert "tools" not in payload
    assert json.loads(payload["input"]) == {
        "public_brief": BRIEF,
        "source_claims": [CLAIM],
        "analysis": {"focus": "stock"},
        "eligible_options": [option.model_dump() for option in options],
    }
