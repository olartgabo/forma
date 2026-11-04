"""MetaMuse design comparison through the real gateway and a scripted transport.

No provider is contacted; SYNTHETIC inputs. Software transport tests, not a
live pass and not a physical result.
"""

import json
import sqlite3

import pytest
from test_synthesis_routes import identity, post, search, setup  # noqa: F401

from forma_api import design_runtime
from forma_api.model_gateway import GatewayError, MetaGateway, Tool
from forma_api.synthesis_muse import CompareDesignsArgs, CompareDesignsResult


class Scripted:
    """Calls the tool from the server's allowlists, then explains the result."""

    def __init__(self, tool_args=None, explanation=None, on_final=None):
        self.calls = []
        self.tool_args = tool_args
        self.explanation = explanation
        self.on_final = on_final

    def post(self, path, payload, timeout):
        self.calls.append(json.loads(json.dumps(payload)))
        content = json.loads(payload["messages"][1]["content"][0]["text"])
        context = content["untrusted_context"]
        usage = {"prompt_tokens": 90, "completion_tokens": 30}
        if "tools" in payload:
            first = context["allowed_candidate_ids"][0]
            depth = context["allowed_probe_values"][first]["footprint_depth_mm"][-1]
            args = (
                self.tool_args(context)
                if self.tool_args
                else {
                    "search_id": context["search_id"],
                    "candidate_ids": context["allowed_candidate_ids"],
                    "probe": {
                        "candidate_id": first,
                        "parameter": "footprint_depth_mm",
                        "value_mm": depth,
                    },
                }
            )
            call = {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": payload["tools"][0]["function"]["name"],
                    "arguments": json.dumps(args),
                },
            }
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {"tool_calls": [call]},
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
                "search_id": result["search_id"],
                "summary": "Both designs fit the saved stock; stability is unmeasured.",
                "candidate_notes": [
                    {"candidate_id": c["candidate_id"], "note": "Explained."}
                    for c in result["candidates"]
                ],
                "unresolved": ["Stability needs measurements of the built stand."],
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
def muse(setup, monkeypatch):  # noqa: F811
    client, project, directory, holder = setup
    transport = {}
    monkeypatch.setattr(
        design_runtime,
        "default_gateway_factory",
        lambda: MetaGateway(transport["t"], max_retries=0, sleep=lambda _: None),
    )
    result = search(client, project)

    def ask(scripted=None, key="design-muse-0001", **extra):
        transport["t"] = scripted or Scripted()
        body = identity(
            project,
            search_id=result["search_id"],
            idempotency_key=key,
            provider_context_consented=True,
        )
        return post(client, project, "muse-explanations", body | extra)

    return client, project, directory, result, ask, transport


def receipts(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute(
            "SELECT key, response FROM requests WHERE scope LIKE '%:synthesis-muse'"
        ).fetchall()


def plans(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0]


def test_tool_compares_authorized_designs_and_probe_is_the_engines(muse):
    client, project, directory, result, ask, transport = muse
    response = ask()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tool_name"] == "compare_stand_designs"
    assert body["physical_status"] == "not_verified"
    assert body["usage"]["input_tokens"] == 180
    probe = body["engine_probe"]
    assert probe["status"] == "evaluated"
    assert set(probe["changed_piece_ids"]) == {"stand-base", "stand-brace"}
    assert probe["report"]["status"] == "acceptable"
    tool_result = json.loads(transport["t"].calls[-1]["messages"][-1]["content"])
    for line in tool_result["candidates"]:
        statuses = {c["check_id"]: c["status"] for c in line["checks"]}
        assert statuses["stability-tip-portrait"] == "missing_input"
    assert plans(directory) == 0
    calls = len(transport["t"].calls)
    replay = ask(Scripted())
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["explanation"] == body["explanation"]
    assert len(transport["t"].calls) == 0 and calls == 2


def test_consent_and_stale_search_block_before_dispatch(muse):
    client, project, directory, result, ask, transport = muse
    scripted = Scripted()
    denied = ask(scripted, provider_context_consented=False)
    assert denied.status_code == 422 and denied.json()["code"] == "consent_required"
    stale = ask(scripted, search_id="b" * 64)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    assert scripted.calls == [] and receipts(directory) == []


@pytest.mark.parametrize(
    "args",
    [
        lambda c: {"search_id": "c" * 64, "candidate_ids": c["allowed_candidate_ids"]},
        lambda c: {"search_id": c["search_id"], "candidate_ids": ["cand-foreign"]},
        lambda c: {
            "search_id": c["search_id"],
            "candidate_ids": c["allowed_candidate_ids"],
            "stand_mass_g": 120,
        },
        lambda c: {
            "search_id": c["search_id"],
            "candidate_ids": c["allowed_candidate_ids"][:1],
            "probe": {
                "candidate_id": c["allowed_candidate_ids"][0],
                "parameter": "lip_mm",
                "value_mm": 20,
            },
        },
    ],
)
def test_model_cannot_pick_foreign_identities_or_supply_inputs(muse, args):
    client, project, directory, result, ask, transport = muse
    response = ask(Scripted(tool_args=args))
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "invalid_response"
    assert receipts(directory) == []
    assert ask(Scripted(), key="design-muse-0002").status_code == 200


def test_off_grid_probe_is_refused_by_the_engine(muse):
    client, project, directory, result, ask, transport = muse

    def args(c):
        first = c["allowed_candidate_ids"][0]
        return {
            "search_id": c["search_id"],
            "candidate_ids": [first],
            "probe": {
                "candidate_id": first,
                "parameter": "part_width_mm",
                "value_mm": 71.3,
            },
        }

    response = ask(Scripted(tool_args=args))
    assert response.status_code == 200, response.text
    assert response.json()["engine_probe"]["status"] == "outside_domain"
    assert response.json()["engine_probe"]["report"] is None


def test_explanation_citing_an_unreturned_design_is_rejected(muse):
    client, project, directory, result, ask, transport = muse

    def explanation(tool_result):
        return {
            "search_id": tool_result["search_id"],
            "summary": "Cites a design the tool did not return.",
            "candidate_notes": [{"candidate_id": "cand-other", "note": "x"}],
        }

    response = ask(Scripted(explanation=explanation))
    assert response.status_code == 502 and receipts(directory) == []


def test_project_change_during_dispatch_saves_a_stale_receipt(muse):
    client, project, directory, result, ask, transport = muse

    def change():
        updated = client.put(
            f"/api/projects/{project['id']}/inventory",
            headers={"Authorization": "Bearer " + "a" * 40},
            json={
                "expected_revision_id": project["revision_id"],
                "idempotency_key": "inventory-during-muse",
                "stocks": project["stocks"],
                "user_confirmed": True,
            },
        )
        assert updated.status_code == 200, updated.text

    response = ask(Scripted(on_final=change))
    assert response.status_code == 409 and response.json()["code"] == "stale_version"
    [(_, saved)] = receipts(directory)
    assert json.loads(saved)["error_code"] == "stale_version"


def test_unknown_provider_outcome_halts_further_requests(muse):
    client, project, directory, result, ask, transport = muse

    class Timeout(Scripted):
        def post(self, path, payload, timeout):
            raise GatewayError("timeout")

    first = ask(Timeout())
    assert first.status_code == 409
    assert first.json()["code"] == "generation_outcome_unknown"
    again = ask(Scripted(), key="design-muse-0002")
    assert again.json()["code"] == "generation_outcome_unknown"


def test_compare_tool_is_allowlisted_and_strict():
    Tool("compare_stand_designs", CompareDesignsArgs, CompareDesignsResult, id)
    with pytest.raises(ValueError):
        Tool("propose_geometry", CompareDesignsArgs, CompareDesignsResult, id)
    assert CompareDesignsArgs.model_config["extra"] == "forbid"


def test_change_after_the_last_resolve_still_saves_a_stale_receipt(muse, monkeypatch):
    client, project, directory, result, ask, transport = muse
    from forma_api import synthesis_runtime

    original = synthesis_runtime.resolve
    calls = []

    def resolve_then_change(*args, **kwargs):
        resolved = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            # Lands after the final freshness read, before the save.
            updated = client.put(
                f"/api/projects/{project['id']}/inventory",
                headers={"Authorization": "Bearer " + "a" * 40},
                json={
                    "expected_revision_id": project["revision_id"],
                    "idempotency_key": "inventory-after-resolve",
                    "stocks": project["stocks"],
                    "user_confirmed": True,
                },
            )
            assert updated.status_code == 200, updated.text
        return resolved

    monkeypatch.setattr(synthesis_runtime, "resolve", resolve_then_change)
    response = ask()
    assert len(calls) == 2
    assert response.status_code == 409 and response.json()["code"] == "stale_version"
    [(_, saved)] = receipts(directory)
    assert json.loads(saved)["error_code"] == "stale_version"
