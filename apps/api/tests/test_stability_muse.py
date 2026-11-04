"""MetaMuse stability tools through the real gateway and an offline scripted transport.

No provider is contacted. These are software transport tests, not a live pass.
"""

import copy
import json
import sqlite3
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from test_plans import AUTH, OTHER, TOKENS
from test_stability_measurements import capture_payload, measurement_url
from test_stability_reports import save

from forma_api.model_gateway import GatewayError, MetaGateway, Tool
from forma_api.projects import ProjectStore
from forma_api.routes.stability_muse import stability_muse_router

pytest_plugins = ["test_stability_route"]


class Scripted:
    """Answers the tool round from the server's allowlist, then explains the result."""

    def __init__(self, tool_args=None, explanation=None, on_final=None):
        self.calls = []
        self.tool_args = tool_args
        self.explanation = explanation
        self.on_final = on_final

    def post(self, path, payload, timeout):
        self.calls.append(json.loads(json.dumps(payload)))
        content = json.loads(payload["messages"][1]["content"][0]["text"])
        context = content["untrusted_context"]
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        if "tools" in payload:
            name = payload["tools"][0]["function"]["name"]
            args = (
                self.tool_args(context)
                if self.tool_args
                else {"case_ids": context["allowed_case_ids"]}
                | (
                    {"plan_version_id": context["allowed_plan_version_id"]}
                    if name == "analyze_stability"
                    else {"report_id": context["allowed_report_ids"][0]}
                )
            )
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ]
                        },
                    }
                ],
                "usage": usage,
            }
        if self.on_final:
            self.on_final()
        result = json.loads(payload["messages"][-1]["content"])
        explanation = (
            self.explanation(result)
            if self.explanation
            else {
                "report_id": result["report_id"],
                "summary": "Modeled tipping result explained from the tool output.",
                "case_notes": [
                    {"case_id": case["case_id"], "note": "Explained modeled case."}
                    for case in result["cases"]
                ],
            }
        )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(explanation)},
                }
            ],
            "usage": usage,
        }


@pytest.fixture
def muse(connected):
    client, url, payload, directory = connected
    store = ProjectStore(directory)
    holder = {}

    def authenticate(authorization: Annotated[str | None, Header()] = None):
        for owner, token in TOKENS.items():
            if authorization == "Bearer " + token:
                return owner
        raise HTTPException(401)

    def factory():
        return MetaGateway(holder["transport"], max_retries=0, sleep=lambda _: None)

    client.app.include_router(
        stability_muse_router(store, authenticate, gateway_factory=factory),
        prefix="/muse",
    )
    project_id = url.split("/")[2]
    endpoint = f"/muse/{project_id}/stability/muse-explanations"

    def ask(body, transport=None, key="muse-key-0001", headers=AUTH, **extra):
        holder["transport"] = transport or Scripted()
        request = {
            k: body[k]
            for k in (
                "plan_version_id",
                "expected_inventory_revision_id",
                "expected_last_event_id",
            )
        } | dict(
            idempotency_key=key,
            mode="analyze_current",
            provider_context_consented=True,
        )
        return client.post(endpoint, headers=headers, json=request | extra)

    return client, url, directory, ask


def measured(connected):
    client, url, _, _ = connected
    body = capture_payload(connected)
    saved = client.post(measurement_url(url), headers=AUTH, json=body).json()
    return body | {"expected_last_event_id": saved["last_event_id"]}


def saved_reports(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        return db.execute("SELECT id, body FROM stability_reports").fetchall()


def requests(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        return db.execute(
            "SELECT key, response FROM requests WHERE scope LIKE '%:stability-muse'"
        ).fetchall()


def test_tool_engine_stored_report_and_history_flow(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)
    transport = Scripted()
    response = ask(body, transport)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tool_name"] == "analyze_stability"
    assert result["physical_status"] == "not_verified"
    assert result["usage"] == {
        "model_calls": 2,
        "input_tokens": 200,
        "output_tokens": 40,
    }
    report_id = result["report"]["report_id"]
    assert result["explanation"]["report_id"] == report_id
    assert result["report"]["source"] == "muse_tool"
    assert result["report"]["freshness"]["current"] is True
    stored = saved_reports(directory)
    assert [row[0] for row in stored] == [report_id]
    # The tool result the model saw is the engine report that was stored.
    tool_result = json.loads(transport.calls[1]["messages"][-1]["content"])
    saved = json.loads(stored[0][1])
    assert tool_result["report_id"] == report_id
    assert tool_result["report_status"] == saved["report"]["status"] == "modeled_pass"
    assert tool_result["physical_status"] == "not_verified"
    # Only the bounded allowlist and tool output reach the provider; no evidence
    # descriptions, media or measurement free text are placed in the context.
    first = json.dumps(transport.calls[0])
    assert "User-reported typed assembled" not in first
    assert "Synthetic ruler contact" not in first
    assert transport.calls[0]["tools"][0]["function"]["name"] == "analyze_stability"
    history = client.get(
        url.replace("/test/", "/api/projects/").removesuffix("analyses") + "reports",
        headers=AUTH,
    ).json()
    assert history["reports"][0]["report_id"] == report_id
    # Builder save of the same state reuses the content-addressed Muse report.
    builder = save(client, url, body, body["expected_last_event_id"], "builder-k-001")
    assert builder.json()["cached"] is True
    assert builder.json()["saved"]["report_id"] == report_id
    replay = ask(body, Scripted())
    assert replay.json()["replayed"] is True
    assert replay.json()["report"]["report_id"] == report_id


def test_consent_and_missing_report_block_before_dispatch(connected, muse):
    client, url, directory, ask = muse
    transport = Scripted()
    _, _, payload, _ = connected
    refused = ask(payload, transport, provider_context_consented=False)
    assert refused.status_code == 422
    assert refused.json()["code"] == "consent_required"
    blocked = ask(payload, transport, key="muse-key-0002")
    assert blocked.status_code == 422 and blocked.json()["code"] == "blocked"
    assert transport.calls == [] and requests(directory) == []
    stale = ask(measured(connected) | {"expected_last_event_id": None}, transport)
    assert stale.status_code == 409 and transport.calls == []


@pytest.mark.parametrize(
    "args",
    [
        lambda c: {"plan_version_id": "plan-other", "case_ids": ["portrait"]},
        lambda c: {
            "plan_version_id": c["allowed_plan_version_id"],
            "case_ids": ["portrait", "upside-down"],
        },
        lambda c: {
            "plan_version_id": c["allowed_plan_version_id"],
            "case_ids": ["portrait"],
            "measurements": {"stand": {"mass_kg": 99}},
        },
        lambda c: {
            "plan_version_id": c["allowed_plan_version_id"],
            "case_ids": ["portrait"],
            "user_confirmed": True,
        },
    ],
)
def test_model_cannot_choose_foreign_identity_or_supply_trusted_inputs(
    connected, muse, args
):
    client, url, directory, ask = muse
    body = measured(connected)
    response = ask(body, Scripted(tool_args=args))
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "invalid_response"
    assert saved_reports(directory) == []
    assert requests(directory) == []
    retry = ask(body, Scripted())
    assert retry.status_code == 200, retry.text


def test_explanation_citing_another_report_is_rejected(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)

    def wrong(result):
        return {"report_id": "stability-report-" + "f" * 64, "summary": "Wrong"}

    def unknown_case(result):
        return {
            "report_id": result["report_id"],
            "summary": "Mentions an unselected case",
            "case_notes": [{"case_id": "upside-down", "note": "fabricated"}],
        }

    for explanation in (wrong, unknown_case):
        response = ask(body, Scripted(explanation=explanation))
        assert response.status_code == 502, response.text
        assert saved_reports(directory) == []


def test_explain_report_reads_stale_history_without_new_writes(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)
    first = save(client, url, body, body["expected_last_event_id"], "explain-k-001")
    report_id = first.json()["saved"]["report_id"]
    changed = copy.deepcopy(body)
    changed["idempotency_key"] = "measurements-009"
    changed["measurements"]["cases"][0]["device"]["mass_kg"] = 0.25
    event = client.post(measurement_url(url), headers=AUTH, json=changed).json()[
        "last_event_id"
    ]
    current = body | {"expected_last_event_id": event}
    transport = Scripted(
        explanation=lambda r: {
            "report_id": r["report_id"],
            "summary": "This older report is stale.",
        }
    )
    response = ask(current, transport, mode="explain_report", report_id=report_id)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tool_name"] == "explain_stability_inputs"
    assert result["report"]["freshness"]["stale_reasons"] == ["history_changed"]
    tool_result = json.loads(transport.calls[1]["messages"][-1]["content"])
    assert tool_result["freshness"]["current"] is False
    masses = {
        b["body_id"]: b["mass"]["value"]
        for case in tool_result["cases"]
        for b in case["bodies"]
    }
    assert masses["device-portrait"] == 0.2
    assert all(
        b["mass"]["provenance"] == "measured" for b in tool_result["cases"][0]["bodies"]
    )
    assert [row[0] for row in saved_reports(directory)] == [report_id]
    missing = ask(
        current,
        Scripted(),
        key="muse-key-0003",
        mode="explain_report",
        report_id="stability-report-" + "0" * 64,
    )
    assert missing.status_code == 404
    foreign = ask(
        current,
        Scripted(),
        key="muse-key-0004",
        headers=OTHER,
        mode="explain_report",
        report_id=report_id,
    )
    assert foreign.status_code == 404
    invalid = ask(current, Scripted(), key="muse-key-0005", report_id=report_id)
    assert invalid.status_code == 422


def test_unknown_provider_outcome_halts_further_requests(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)

    class Timeout(Scripted):
        def post(self, path, payload, timeout):
            raise GatewayError("timeout")

    first = ask(body, Timeout())
    assert first.status_code == 409
    assert first.json()["code"] == "generation_outcome_unknown"
    again = ask(body, Scripted(), key="muse-key-0002")
    assert again.status_code == 409
    assert again.json()["code"] == "generation_outcome_unknown"
    assert saved_reports(directory) == []
    assert json.loads(requests(directory)[0][1])["uncertain"] is True


def test_history_change_during_dispatch_saves_nothing(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)
    project_id = url.split("/")[2]

    def record_event():
        with sqlite3.connect(directory / "projects.sqlite3") as db:
            row = db.execute(
                "SELECT version_id, body FROM progress_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            event = json.loads(row[1]) | {"id": "event-concurrent"}
            db.execute(
                "INSERT INTO progress_events VALUES (?, ?, ?, ?)",
                ("event-concurrent", project_id, row[0], json.dumps(event)),
            )

    response = ask(body, Scripted(on_final=record_event))
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "stale_version"
    assert saved_reports(directory) == []
    replay = ask(body, Scripted())
    assert replay.status_code == 409 and replay.json()["code"] == "stale_version"


def test_in_progress_request_blocks_duplicates(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)
    project_id = url.split("/")[2]
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        db.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
            (
                "alice",
                project_id + ":stability-muse",
                "other-key-01",
                "x",
                '{"pending": true}',
            ),
        )
    transport = Scripted()
    response = ask(body, transport)
    assert response.status_code == 409
    assert response.json()["code"] == "generation_in_progress"
    assert transport.calls == []


def test_only_allowlisted_stability_tools_are_registered():
    from forma_api.stability_muse import AnalyzeStabilityArgs, AnalyzeStabilityResult

    for name in ("analyze_stability", "explain_stability_inputs"):
        Tool(name, AnalyzeStabilityArgs, AnalyzeStabilityResult, lambda a: a)
    with pytest.raises(ValueError):
        Tool("save_measurements", AnalyzeStabilityArgs, AnalyzeStabilityResult, id)


def test_completed_request_with_lost_response_replays_without_dispatch(connected, muse):
    client, url, directory, ask = muse
    body = measured(connected)
    first = ask(body, Scripted(), key="lost-response-1")
    assert first.status_code == 200, first.text
    # The browser never saw that response; meanwhile measurements changed in
    # another tab, so the retained request identity is now stale.
    changed = copy.deepcopy(body)
    changed["idempotency_key"] = "measurements-010"
    changed["measurements"]["stand"]["mass_kg"] = 0.12
    moved = client.post(measurement_url(url), headers=AUTH, json=changed)
    assert moved.status_code == 200, moved.text
    transport = Scripted()
    retry = ask(body, transport, key="lost-response-1")
    assert retry.status_code == 200, retry.text
    assert transport.calls == [], "a completed request is never sent again"
    result = retry.json()
    assert result["replayed"] is True
    assert result["explanation"] == first.json()["explanation"]
    assert result["report"]["report_id"] == first.json()["report"]["report_id"]
    assert result["report"]["freshness"] == {
        "current": False,
        "stale_reasons": ["history_changed"],
    }
    assert len(saved_reports(directory)) == 1
    # A different key for the stale identity is still refused before dispatch.
    fresh_key = ask(body, transport, key="lost-response-2")
    assert fresh_key.status_code == 409 and transport.calls == []
