"""Synthetic repair searches over saved history; no physical attempt or pass."""

import json
import sqlite3

import pytest
import test_adapt
import test_progress
from test_adapt import active, commit, joined, progress, report_damage
from test_plans import AUTH, OTHER

from forma_api import adapt, fabrication_runtime
from forma_domain.models import BuildPlan

repair_setup = test_adapt.setup
spare_free_setup = test_progress.setup
preview_setup = test_progress.preview_setup


@pytest.fixture
def setup(repair_setup, monkeypatch):
    monkeypatch.setattr(fabrication_runtime, "ALLOW_SYNTHETIC", True)
    client, version, directory = repair_setup
    # Explicit synthetic tool declaration; strict readiness must not invent it.
    set_tools(directory, version.project_id, ["ruler", "scissors"])
    return repair_setup


def set_tools(directory, project_id, tools):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        row = connection.execute(
            "SELECT body FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project = json.loads(row[0])
        project["requirements"]["tools"] = tools
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?", (json.dumps(project), project_id)
        )


def search(client, plan, current, key="search-001", headers=AUTH, **fields):
    body = dict(
        expected_version_id=plan.version_id,
        expected_last_event_id=current["last_event_id"],
        idempotency_key=key,
        connector_measurements=[
            {"stock_id": stock["id"], "remaining_length_mm": 260}
            for stock in current["expected_remaining_stock"]
            if stock["kind"] == "tape"
            and stock["remaining_length_mm"]["source"] == "calculated"
            and not stock["remaining_length_mm"]["confirmed"]
        ],
        remaining_confirmed=True,
    )
    body.update(fields)
    return client.post(
        f"/api/projects/{plan.project_id}/repairs/search", headers=headers, json=body
    )


def events(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return connection.execute("SELECT COUNT(*) FROM progress_events").fetchone()[0]


def outcomes(summary):
    return {
        (o["patch"]["kind"], o["patch"]["target_id"]): o for o in summary["outcomes"]
    }


def test_scope_staleness_and_missing_targets(setup):
    client, version, _ = setup
    plan = version.plan
    current = progress(client, plan.project_id, plan.version_id)
    assert search(client, plan, current, headers={}).status_code == 401
    foreign = search(client, plan, current, headers=OTHER)
    assert foreign.status_code == 404
    assert plan.version_id not in foreign.text
    stale = search(client, plan, {**current, "last_event_id": "event-elsewhere"})
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_version"
    # Nothing failed or broke, so there is nothing to search for.
    nothing = search(client, plan, current, key="search-002")
    assert nothing.status_code == 409
    assert nothing.json()["code"] == "blocked"
    unknown = search(client, plan, current, key="search-003", target_ids=["no-part"])
    assert unknown.status_code == 422


def test_damaged_brace_search_ranks_the_tape_undo_and_approves_atomically(setup):
    client, version, directory = setup
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    before = events(directory)
    response = search(client, plan, damaged)
    assert response.status_code == 200, response.text
    result = response.json()
    summary = result["summary"]
    assert summary["status"] == "found"
    assert summary["target_ids"] == ["stand-brace"]
    assert summary["stability_coverage"] == "unverified"
    assert summary["unknown_cost_terms"] == ["time", "purchase_price", "strength"]
    by_kind = outcomes(summary)
    replace = by_kind[("replace_part", "stand-brace")]
    assert replace["status"] == "ranked" and replace["rank"] == 1
    assert replace["patch"]["replacement_stock_id"] == "synthetic-spare"
    # Swapping a tape hinge for a fold profile changes the joint strategy,
    # which the stand family still rejects.
    swaps = [
        o for o in summary["outcomes"] if o["patch"]["kind"] == "replace_joint_profile"
    ]
    assert swaps and all(o["status"] == "infeasible" and o["blockers"] for o in swaps)
    assert summary["evaluated_count"] == summary["generated_count"] == 1 + len(swaps)

    preview = result["previews"]["previews"][0]
    assert preview["preview_id"] == replace["preview_id"]
    simulation = preview["simulation"]
    assert len(simulation["required_undo_operation_ids"]) == 2
    assert simulation["lost_part_ids"] == ["stand-brace"]
    # Base and support work is kept; only the brace and its hinges change.
    assert {
        "stand-cut-panels",
        "stand-fold-lip",
        "stand-joint-front-attach",
    } <= set(simulation["preserved_operation_ids"])
    assert not {"stand-base", "stand-support"} & set(simulation["changed_part_ids"])
    assert preview["panel_diff"]["unchanged"] == [0, 1, 2, 3, 4, 5]
    # Searching records no physical work and changes no active state.
    assert events(directory) == before
    assert active(client, plan.project_id) == plan.version_id
    assert progress(client, plan.project_id, plan.version_id) == damaged

    replay = search(client, plan, damaged)
    assert replay.json() == {**result, "replayed": True}
    conflict = search(client, plan, damaged, max_evaluated=1)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    stale = commit(
        client,
        plan,
        {**damaged, "last_event_id": "event-elsewhere"},
        preview["preview_id"],
        key="commit-stale",
    )
    assert stale.status_code == 409
    approved = commit(client, plan, damaged, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    assert active(client, plan.project_id) == preview["version"]["version_id"]
    assert events(directory) == before
    assert progress(client, plan.project_id, plan.version_id) == damaged


def test_evaluation_limit_reports_exhausted_rather_than_infeasible(setup):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    # The rear-joint swap is generated first and fails; the limit stops the
    # search before the brace replacement that would have passed.
    response = search(
        client,
        plan,
        current,
        target_ids=["stand-joint-rear", "stand-brace"],
        max_evaluated=1,
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["status"] == "exhausted"
    assert summary["evaluated_count"] == 1
    assert summary["generated_count"] > 1
    assert [o["status"] for o in summary["outcomes"]][:2] == [
        "infeasible",
        "not_evaluated",
    ]
    assert response.json()["previews"]["previews"] == []


def test_without_spare_stock_the_search_is_honestly_infeasible(
    spare_free_setup, monkeypatch
):
    monkeypatch.setattr(adapt, "ALLOW_SYNTHETIC", True)
    monkeypatch.setattr(fabrication_runtime, "ALLOW_SYNTHETIC", True)
    client, version, _ = spare_free_setup
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    response = search(client, plan, damaged)
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["status"] == "infeasible"
    assert summary["evaluated_count"] == summary["generated_count"]
    # No sheet has a usable region left, so no replacement is even proposed.
    assert all(o["patch"]["kind"] != "replace_part" for o in summary["outcomes"])
    assert response.json()["previews"]["previews"] == []


def test_second_repair_of_a_replacement_stays_unsupported(setup):
    client, version, _ = setup
    plan = version.plan
    damaged = report_damage(client, plan, joined(client, version))
    first = search(client, plan, damaged).json()
    preview = first["previews"]["previews"][0]
    assert commit(client, plan, damaged, preview["preview_id"]).status_code == 200
    revised = BuildPlan.model_validate(preview["version"]["plan"])
    original = {p.id for p in plan.parts}
    replacement = next(p.id for p in revised.parts if p.id not in original)
    current = progress(client, plan.project_id, revised.version_id)
    response = search(
        client, revised, current, key="search-second", target_ids=[replacement]
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["status"] == "infeasible"
    assert all(o["status"] != "ranked" for o in summary["outcomes"])


def test_missing_declared_cutting_tool_blocks_repair_search(setup):
    client, version, directory = setup
    set_tools(directory, version.project_id, ["ruler"])
    damaged = report_damage(client, version.plan, joined(client, version))
    result = search(client, version.plan, damaged).json()
    assert result["summary"]["status"] == "infeasible"
    assert result["previews"]["previews"] == []
    replacement = next(
        o for o in result["summary"]["outcomes"] if o["patch"]["kind"] == "replace_part"
    )
    assert any("cutting tool" in b["message"] for b in replacement["blockers"])
