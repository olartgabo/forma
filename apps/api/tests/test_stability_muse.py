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
                "case_ids": [case["case_id"] for case in result["cases"]][:2],
                "check_types": ["tip"],
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
            "case_ids": ["portrait"],
            "check_types": ["tip"],
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


@pytest.mark.parametrize(
    "change",
    [
        "unsafe_prose",
        "foreign_case",
        "foreign_check",
        "absent_check",
        "empty",
        "duplicate",
        "too_many",
    ],
)
def test_closed_focus_rejects_model_prose_and_foreign_selectors(
    connected, muse, change
):
    _, _, directory, ask = muse
    body = measured(connected)

    def invalid(result):
        focus = dict(
            report_id=result["report_id"], case_ids=["portrait"], check_types=["tip"]
        )
        if change == "unsafe_prose":
            focus.update(
                summary="Physical test passed. Certified safe.",
                case_notes=[dict(case_id="portrait", note="Approved physical test")],
            )
        elif change == "foreign_case":
            focus["case_ids"] = ["upside-down"]
        elif change == "foreign_check":
            focus["check_types"] = ["certified-safe"]
        elif change == "absent_check":
            focus["check_types"] = ["joint"]
        elif change == "empty":
            focus["case_ids"] = []
        elif change == "duplicate":
            focus["check_types"] = ["tip", "tip"]
        else:
            focus["case_ids"] = ["portrait", "landscape", "third"]
        return focus

    transport = Scripted(explanation=invalid)
    response = ask(body, transport)
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "invalid_response"
    assert "Certified safe" not in response.text
    assert len(transport.calls) == 2
    assert saved_reports(directory) == []


@pytest.mark.parametrize(
    "status,selected_case",
    [
        ("modeled_fail", "landscape"),
        ("modeled_fail", "portrait"),
        ("indeterminate", "landscape"),
    ],
)
def test_focus_preserves_aggregate_failure_and_actual_selected_status(
    connected, muse, status, selected_case
):
    client, url, directory, ask = muse
    body = measured(connected)
    first = save(
        client, url, body, body["expected_last_event_id"], "focus-reference"
    ).json()
    changed = copy.deepcopy(body)
    changed["idempotency_key"] = "focus-measurements-02"
    if status == "modeled_fail":
        changed["measurements"]["cases"][1]["device"]["center_of_mass_m"]["x"] = 1.0
    else:
        changed["measurements"]["required_margin_m"] = first["analysis"]["report"][
            "overlays"
        ][0]["signed_margin_m"]
    receipt = client.post(measurement_url(url), headers=AUTH, json=changed)
    assert receipt.status_code == 200, receipt.text
    current = body | {"expected_last_event_id": receipt.json()["last_event_id"]}
    transport = Scripted(
        explanation=lambda result: dict(
            report_id=result["report_id"], case_ids=[selected_case], check_types=["tip"]
        )
    )
    response = ask(current, transport)
    assert response.status_code == 200, response.text
    result = response.json()
    report = next(
        json.loads(row[1])["report"]
        for row in saved_reports(directory)
        if row[0] == result["report"]["report_id"]
    )
    row = next(
        row
        for row in report["results"]
        if row["case_id"] == selected_case and row["check_type"] == "tip"
    )
    assert report["status"] == status
    assert (
        result["explanation"]["summary"]
        == f"Saved report status: {status}. Selected result counts: {row['status']}: 1."
    )
    assert row["status"] in result["explanation"]["case_notes"][0]["note"]
    assert result["focused_results"] == [row]
    assert result["explanation"]["questions"] == []
    assert (
        "cannot establish a physical test pass, safety certification"
        in result["explanation"]["missing_inputs"][0]
    )
    assert result["usage"] == dict(model_calls=2, input_tokens=200, output_tokens=40)
    replay_transport = Scripted()
    replay = ask(current, replay_transport)
    assert replay.json() == result | {"replayed": True}
    assert replay_transport.calls == []


def legacy_digest(body, project_id, key):
    from forma_api.routes.designs import _digest
    from forma_api.stability_muse import LEGACY_PROMPT_VERSION, StabilityMuseRequest

    request = StabilityMuseRequest.model_validate(
        {
            k: body[k]
            for k in (
                "plan_version_id",
                "expected_inventory_revision_id",
                "expected_last_event_id",
            )
        }
        | dict(
            idempotency_key=key, mode="analyze_current", provider_context_consented=True
        )
    )
    return _digest(
        dict(
            request=request.model_dump(mode="json"),
            project_id=project_id,
            prompt_version=LEGACY_PROMPT_VERSION,
        )
    )


def test_legacy_completed_receipt_replays_engine_text_without_provider_or_old_prose(
    connected, muse
):
    client, url, directory, ask = muse
    body = measured(connected)
    first = ask(body, Scripted(), key="legacy-receipt-01")
    assert first.status_code == 200, first.text
    legacy = first.json()
    legacy.pop("focus")
    legacy.pop("focused_results")
    legacy["prompt_version"] = "stability-explanation-v1"
    legacy["explanation"] = dict(
        report_id=legacy["report"]["report_id"],
        summary="Physical test passed. Certified safe.",
        case_notes=[dict(case_id="portrait", note="Certified safe")],
    )
    project_id = url.split("/")[2]
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        db.execute(
            "UPDATE requests SET digest=?,response=? WHERE key=? AND scope=?",
            (
                legacy_digest(body, project_id, "legacy-receipt-01"),
                json.dumps(legacy),
                "legacy-receipt-01",
                project_id + ":stability-muse",
            ),
        )
    changed = copy.deepcopy(body)
    changed["idempotency_key"] = "legacy-measurements-02"
    changed["measurements"]["stand"]["mass_kg"] = 0.12
    assert (
        client.post(measurement_url(url), headers=AUTH, json=changed).status_code == 200
    )
    transport = Scripted()
    response = ask(body, transport, key="legacy-receipt-01")
    assert response.status_code == 200, response.text
    assert response.json()["replayed"]
    assert response.json()["prompt_version"] == "stability-focus-v2"
    assert response.json()["usage"] == first.json()["usage"]
    assert response.json()["report"]["freshness"]["current"] is False
    assert response.json()["focus"]["case_ids"]
    assert "Certified safe" not in response.text
    assert "Physical test passed" not in response.text
    assert transport.calls == []


@pytest.mark.parametrize("uncertain", [False, True])
def test_legacy_pending_and_unknown_receipts_block_same_and_changed_key(
    connected, muse, uncertain
):
    _, url, directory, ask = muse
    body = measured(connected)
    project_id = url.split("/")[2]
    marker = {"pending": True} | (
        {"uncertain": True, "error_code": "timeout"} if uncertain else {}
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        db.execute(
            "INSERT INTO requests VALUES (?,?,?,?,?)",
            (
                "alice",
                project_id + ":stability-muse",
                "legacy-receipt-01",
                legacy_digest(body, project_id, "legacy-receipt-01"),
                json.dumps(marker),
            ),
        )
    transport = Scripted()
    for key in ("legacy-receipt-01", "changed-receipt-02"):
        response = ask(body, transport, key=key)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == (
            "generation_outcome_unknown" if uncertain else "generation_in_progress"
        )
    assert transport.calls == []


def test_zero_result_legacy_receipt_blocks_without_dispatch(
    connected, muse, monkeypatch
):
    from forma_api import stability_reports as reports

    _, url, directory, ask = muse
    body = measured(connected)
    first = ask(body, Scripted(), key="legacy-empty-01")
    assert first.status_code == 200, first.text
    value = first.json()
    value.pop("focus")
    value.pop("focused_results")
    project_id = url.split("/")[2]
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        db.execute(
            "UPDATE requests SET digest=?,response=? WHERE key=?",
            (
                legacy_digest(body, project_id, "legacy-empty-01"),
                json.dumps(value),
                "legacy-empty-01",
            ),
        )
    original = reports.read_record

    def empty_report(connection, project_id, report_id):
        saved = original(connection, project_id, report_id)
        return saved.model_copy(
            update={
                "report": saved.report.model_copy(
                    update={
                        "results": (),
                        "status": "unsupported",
                        "coverage": "unsupported",
                    }
                )
            }
        )

    monkeypatch.setattr(reports, "read_record", empty_report)
    transport = Scripted()
    response = ask(body, transport, key="legacy-empty-01")
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "blocked"
    assert transport.calls == []
