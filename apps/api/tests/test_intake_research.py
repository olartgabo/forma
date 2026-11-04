"""Offline route checks with real synthesis and a stubbed Meta provider."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from test_intake_research_muse import CLAIM, citation, message, response, search_call
from test_plans import AUTH, OTHER, stand_inputs
from test_synthesis_routes import identity, post, search, state
from test_synthesis_routes import setup as setup

from forma_api import intake_research as runtime
from forma_api.model_gateway import GatewayError

FINDING = runtime.muse.ResearchFinding(
    claim="A cardboard stand can use a taped triangular brace.",
    title="Tabletop stand example",
    url="https://example.org/stand",
)


def body(project, **changes):
    return {
        "expected_inventory_revision_id": project["revision_id"],
        "idempotency_key": "intake-research-1",
        "consented": True,
        "use_case": "phone_stand",
        "needs_plug_clearance": False,
    } | changes


def revise_inventory(client, project, key, *, stocks=None, tools=None):
    requirements = dict(project["requirements"])
    if tools is not None:
        requirements["tools"] = tools
    response = client.put(
        f"/api/projects/{project['id']}/inventory",
        headers=AUTH,
        json={
            "expected_revision_id": project["revision_id"],
            "idempotency_key": key,
            "stocks": project["stocks"] if stocks is None else stocks,
            "requirements": requirements,
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]


@pytest.fixture
def provider(monkeypatch):
    calls = []
    monkeypatch.setenv("FORMA_INTAKE_RESEARCH", "1")
    monkeypatch.setattr(
        runtime.MetaGateway, "from_env", lambda: SimpleNamespace(traces=[])
    )

    def scout(gateway, brief, deadline):
        calls.append(("scout", brief))
        return (FINDING,)

    def analyze(gateway, brief, deadline):
        calls.append(("analyst", brief))
        return runtime.muse.ResearchAnalysis(focus="stock")

    def adjudicate(gateway, brief, findings, analysis, options, deadline):
        calls.append(("adjudicator", options))
        assert findings == (FINDING,)
        assert analysis.focus == "stock"
        return options[-1].id

    monkeypatch.setattr(runtime.muse, "scout", scout)
    monkeypatch.setattr(runtime.muse, "analyze", analyze)
    monkeypatch.setattr(runtime.muse, "adjudicate", adjudicate)
    return calls


@pytest.fixture
def ready(setup):
    client, project, directory, holder = setup
    updated = revise_inventory(
        client,
        project,
        "research-tools",
        tools=["ruler", "marker", "scissors", "cutting mat"],
    )
    holder["context"] = holder["context"].model_copy(
        update={"inventory_revision_id": updated["revision_id"]}
    )
    return client, updated, directory, holder


def test_research_recommends_only_checked_candidates_and_uses_normal_preview(
    ready, provider
):
    client, project, directory, _ = ready
    before = state(directory)
    result = post(client, project, "research", body(project))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["coverage"] == "complete", data
    assert data["decision"] == "eligible"
    assert data["findings"] == [FINDING.model_dump(mode="json")]
    engine = search(client, project)
    assert data["search"] == engine
    candidate = engine["candidates"][-1]
    assert data["recommended_candidate_id"] == candidate["candidate_id"]
    assert len(provider) == 3
    assert {detail for role, detail in provider if role != "adjudicator"} == {
        runtime.BRIEFS["phone_stand"]
    }
    assert post(client, project, "research", body(project)).json() == (
        data | {"replayed": True}
    )
    assert len(provider) == 3
    assert (
        post(
            client, project, "research", body(project, use_case="reading_stand")
        ).status_code
        == 409
    )
    after = state(directory)
    assert {k: v for k, v in after.items() if k != "requests"} == {
        k: v for k, v in before.items() if k != "requests"
    }

    preview = post(
        client,
        project,
        "select",
        identity(
            project,
            search_id=engine["search_id"],
            design=candidate["design"],
            idempotency_key="research-preview",
            user_selected=True,
        ),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "accepted"
    assert state(directory)["progress_events"] == before["progress_events"]
    assert state(directory)["projects"] == before["projects"]


def test_scope_consent_and_feature_flag_precede_provider(ready, provider, monkeypatch):
    client, project, _, _ = ready
    path = f"/api/projects/{project['id']}/synthesis/research"
    assert client.get(path, headers=AUTH).json() == {"enabled": True}
    assert client.get(path, headers=OTHER).status_code == 404
    assert post(client, project, "research", body(project), OTHER).status_code == 404
    for consent in (False, 1, 1.0, "true"):
        assert (
            post(
                client, project, "research", body(project, consented=consent)
            ).status_code
            == 422
        )
    assert (
        post(
            client,
            project,
            "research",
            body(project, expected_inventory_revision_id="inventory-old"),
        ).status_code
        == 409
    )
    monkeypatch.delenv("FORMA_INTAKE_RESEARCH")
    assert client.get(path, headers=AUTH).json() == {"enabled": False}
    assert post(client, project, "research", body(project)).status_code == 404
    assert not provider


def test_essential_unknown_and_impossible_stock_stop_before_dispatch(ready, provider):
    client, project, _, holder = ready
    unsupported = post(
        client, project, "research", body(project, needs_plug_clearance=True)
    )
    assert unsupported.status_code == 200, unsupported.text
    assert unsupported.json()["decision"] == "unsupported"
    assert unsupported.json()["search"] is None

    stocks = project["stocks"]
    sheet = stocks[0]
    sheet["width_mm"]["value"] = 40
    sheet["usable_regions"][0]["geometry"]["width"] = 40
    project = revise_inventory(client, project, "research-small-stock", stocks=stocks)
    holder["context"] = holder["context"].model_copy(
        update={"inventory_revision_id": project["revision_id"]}
    )
    blocked = post(client, project, "research", body(project))
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["decision"] == "blocked", blocked.text
    assert blocked.json()["search"] is None
    assert not provider


def test_missing_tools_do_not_become_eligible_through_research(setup, provider):
    client, project, _, _ = setup
    result = post(client, project, "research", body(project))
    assert result.status_code == 200, result.text
    assert result.json()["decision"] == "needs_input", result.text
    assert result.json()["search"] is None
    assert not provider


def test_timeout_replays_partial_result_and_blocks_a_new_dispatch(
    ready, provider, monkeypatch
):
    client, project, _, _ = ready

    def fail(*args):
        raise GatewayError("timeout")

    monkeypatch.setattr(runtime.muse, "analyze", fail)
    first = post(client, project, "research", body(project))
    assert first.status_code == 200, first.text
    assert first.json()["coverage"] == "partial"
    assert first.json()["recommended_candidate_id"] is None
    replay = post(client, project, "research", body(project))
    assert replay.json() == first.json() | {"replayed": True}
    newer = post(
        client, project, "research", body(project, idempotency_key="research-new")
    )
    assert (
        newer.status_code == 409
        and newer.json()["code"] == "generation_outcome_unknown"
    )
    assert len(provider) == 1
    assert search(client, project)["candidates"]


def test_no_sources_and_abstention_leave_engine_candidates_available(
    ready, provider, monkeypatch
):
    client, project, _, _ = ready
    monkeypatch.setattr(
        runtime.muse, "adjudicate", lambda *args: runtime.muse.NO_PREFERENCE
    )
    result = post(client, project, "research", body(project)).json()
    assert result["coverage"] == "complete"
    assert result["recommended_candidate_id"] is None
    assert result["search"] == search(client, project)

    monkeypatch.setattr(runtime.muse, "scout", lambda *args: ())
    result = post(
        client,
        project,
        "research",
        body(project, idempotency_key="research-no-sources"),
    ).json()
    assert result["coverage"] == "no_sources"
    assert result["findings"] == []
    assert result["recommended_candidate_id"] is None
    assert result["search"]["status"] == "candidates_found"


def test_pending_reservation_and_inventory_change_block_late_result(
    ready, provider, monkeypatch
):
    client, project, directory, _ = ready
    started, finish = Event(), Event()

    def scout(*args):
        started.set()
        assert finish.wait(12)
        return (FINDING,)

    monkeypatch.setattr(runtime.muse, "scout", scout)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post, client, project, "research", body(project))
        try:
            assert started.wait(12)
            overlap = post(
                client,
                project,
                "research",
                body(project, idempotency_key="research-overlap"),
            )
            assert overlap.status_code == 409, overlap.text
            assert overlap.json()["code"] == "generation_outcome_unknown"
            revise_inventory(client, project, "research-revised")
        finally:
            finish.set()
        assert pending.result(timeout=12).status_code == 409
    assert not any(runtime.SCOPE in row[1] for row in state(directory)["requests"])


def test_deletion_purges_research_receipts(ready, provider):
    client, project, directory, _ = ready
    assert post(client, project, "research", body(project)).status_code == 200
    assert any(runtime.SCOPE in row[1] for row in state(directory)["requests"])
    deleted = client.delete(
        f"/api/projects/{project['id']}",
        headers={**AUTH, "Idempotency-Key": "research-delete"},
    )
    assert deleted.status_code == 200, deleted.text
    assert not any(runtime.SCOPE in row[1] for row in state(directory)["requests"])


def test_project_deletion_preserves_active_capacity_until_provider_finishes(
    ready, provider, monkeypatch
):
    client, project, directory, holder = ready
    started, finish = Event(), Event()

    def scout(*args):
        started.set()
        assert finish.wait(12)
        return (FINDING,)

    monkeypatch.setattr(runtime.muse, "scout", scout)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post, client, project, "research", body(project))
        try:
            assert started.wait(12)
            deleted = client.delete(
                f"/api/projects/{project['id']}",
                headers={**AUTH, "Idempotency-Key": "research-delete"},
            )
            assert deleted.status_code == 200, deleted.text
            scopes = {row[1] for row in state(directory)["requests"]}
            assert project["id"] + runtime.SCOPE not in scopes
            assert runtime.LEASE_SCOPE in scopes

            created = client.post(
                "/api/projects",
                headers=AUTH,
                json={
                    "goal": "New synthetic stand",
                    "idempotency_key": "research-new-project",
                },
            ).json()["project"]
            new_project = revise_inventory(
                client,
                created | {"requirements": project["requirements"]},
                "research-other-stock",
                stocks=project["stocks"],
            )
            _, _, _, parameters, process, profiles = stand_inputs(new_project["id"])
            holder["context"] = holder["context"].model_copy(
                update={
                    "project_id": new_project["id"],
                    "inventory_revision_id": new_project["revision_id"],
                    "parameters": parameters,
                    "process": process,
                    "joint_profiles": profiles,
                }
            )
            limited = post(client, new_project, "research", body(new_project))
            assert limited.status_code == 429, limited.text
            assert limited.json()["code"] == "rate_limit"
        finally:
            finish.set()
        assert pending.result(timeout=12).status_code == 404
    assert not any(
        runtime.LEASE_SCOPE == row[1] for row in state(directory)["requests"]
    )
    assert post(client, new_project, "research", body(new_project)).status_code == 200


def test_expired_capacity_lease_does_not_hold_global_pool(ready, provider):
    client, project, directory, _ = ready
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.executemany(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "owner-a",
                    runtime.LEASE_SCOPE,
                    "expired-a",
                    "expired-a",
                    '{"expires_at":0}',
                ),
                (
                    "owner-b",
                    runtime.LEASE_SCOPE,
                    "expired-b",
                    "expired-b",
                    '{"expires_at":0}',
                ),
            ],
        )
    result = post(client, project, "research", body(project))
    assert result.status_code == 200, result.text
    assert result.json()["coverage"] == "complete"
    assert not any(
        runtime.LEASE_SCOPE == row[1] for row in state(directory)["requests"]
    )


def test_connected_roles_parse_meta_wire_shape_without_private_project_data(
    ready, monkeypatch
):
    client, project, _, _ = ready
    calls = []

    class Transport:
        def post(self, path, payload, timeout):
            assert path == "/responses" and payload["store"] is False
            assert 0 < timeout <= runtime.DEADLINE_SECONDS
            sent = json.dumps(payload)
            assert project["id"] not in sent
            assert project["revision_id"] not in sent
            assert project["goal"] not in sent
            assert "synthetic-sheet" not in sent
            calls.append(payload)
            if "tools" in payload:
                assert payload["max_tool_calls"] == 1
                result = response(search_call(), message(CLAIM, (citation(),)))
            elif payload["text"]["format"]["name"] == "ResearchAnalysis":
                result = response(message('{"focus":"stock"}'))
            else:
                result = response(message('{"option_id":"option-b"}'))
            return result | {"usage": {"input_tokens": 10, "output_tokens": 3}}

    monkeypatch.setenv("FORMA_INTAKE_RESEARCH", "1")
    monkeypatch.setattr(
        runtime.MetaGateway, "from_env", lambda: runtime.MetaGateway(Transport())
    )
    reply = post(client, project, "research", body(project))
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["coverage"] == "complete"
    assert (
        data["recommended_candidate_id"]
        == data["search"]["candidates"][1]["candidate_id"]
    )
    assert len(calls) == 3
    assert data["usage"] == {"model_calls": 3, "input_tokens": 30, "output_tokens": 9}
