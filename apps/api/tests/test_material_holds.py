"""Material holds during an active build (#177 follow-up, D070).

A held material (an item identified as something its saved stock is not)
pauses current repair and fabrication actions for that build. Recorded
history, saved previews and plan versions stay unchanged, and the active
fabrication report stays readable but is marked blocked. Synthetic fixtures;
no physical result is implied.
"""

import json
import sqlite3

import pytest
import test_fabrication
import test_repair_route
from test_adapt import (
    active,
    commit,
    joined,
    patch,
    progress,
    report_damage,
    simulate,
)
from test_fabrication import assessment, fabrication, preview_fabrication, rows
from test_plans import AUTH, prepared
from test_repair_search import search

from forma_api.plans import PlanService
from forma_api.projects import ProjectError, ProjectStore
from forma_api.recognized_items_runtime import reconcile_existing

setup = test_fabrication.setup
repair_setup = test_fabrication.repair_setup


def item(stock_id, category):
    return {
        "id": "item-" + stock_id,
        "name": "Recognised object",
        "identity": {"outcome": "catalog", "category_id": category},
        "identity_source": "user",
        "user_fields": ["identity"],
        "media_id": None,
        "box": None,
        "box_source": None,
        "visibility": "partial",
        "stock_id": stock_id,
    }


def save_items_directly(directory, project_id, items):
    """An item list saved before reconciliation existed (no hold yet)."""
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS recognized_items "
            "(project_id TEXT PRIMARY KEY, revision TEXT NOT NULL, body TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO recognized_items VALUES (?, ?, ?)",
            (project_id, "items-legacy", json.dumps({"items": items})),
        )


def hold_spare(directory, project_id):
    """The spare sheet was identified as a plastic bottle; held as at startup."""
    save_items_directly(
        directory, project_id, [item("synthetic-spare", "plastic_bottle")]
    )
    assert reconcile_existing(ProjectStore(directory)) == 1


def saved_items(client, project_id):
    return client.get(f"/api/projects/{project_id}/recognized-items", headers=AUTH)


def correct_spare(client, project_id):
    """Change the item back to what the sheet is: an explicit reconciliation."""
    current = saved_items(client, project_id).json()
    response = client.put(
        f"/api/projects/{project_id}/recognized-items",
        headers=AUTH,
        json={
            "expected_revision": current["revision"],
            "idempotency_key": "items-correct-spare",
            "items": [item("synthetic-spare", "corrugated_cardboard")],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == []
    return response.json()


def table_counts(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "progress_events",
                "progress_evidence",
                "adapt_previews",
                "plans",
                "plan_revisions",
            )
        }


def test_a_held_active_build_pauses_repair_and_fabrication_but_keeps_history(
    setup,
):
    client, version, directory = setup
    plan = version.plan
    joined(client, version)
    report_damage(client, plan, progress(client, plan.project_id, plan.version_id))
    current = progress(client, plan.project_id, plan.version_id)
    assert search(client, plan, current, key="search-000").status_code == 200
    hold_spare(directory, plan.project_id)
    before = table_counts(directory)

    found = search(client, plan, current)
    assert (found.status_code, found.json()["code"]) == (409, "blocked"), found.text
    simulated = simulate(client, plan, current, [patch(plan)])
    assert (simulated.status_code, simulated.json()["code"]) == (409, "blocked")
    assessed = assessment(client, version)
    assert (assessed.status_code, assessed.json()["code"]) == (409, "blocked")

    # The active report still reads recorded history, but offers no order.
    report = fabrication(client, plan.project_id, plan.version_id)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["status"] == "blocked"
    assert body["supported_order"] == []
    assert body["next_operation_id"] is None
    held = [b for b in body["blockers"] if b["code"] == "needs_confirmation"]
    assert any(b["target_ids"] == ["synthetic-spare"] for b in held)
    assert body["snapshot"]["last_event_id"] == current["last_event_id"]
    statuses = {o["operation_id"]: o["status"] for o in body["operations"]}
    assert [statuses[o.id] for o in plan.operations[:6]] == ["completed"] * 6

    assert table_counts(directory) == before
    assert progress(client, plan.project_id, plan.version_id) == current
    assert active(client, plan.project_id) == plan.version_id

    # Correcting the item releases the hold; nothing earlier was rewritten.
    correct_spare(client, plan.project_id)
    again = search(client, plan, current, key="search-002")
    assert again.status_code == 200, again.text
    assert assessment(client, version).status_code == 200
    clear = fabrication(client, plan.project_id, plan.version_id).json()
    assert not any(
        b["code"] == "needs_confirmation" and "synthetic-spare" in b["target_ids"]
        for b in clear["blockers"]
    )


def test_a_preview_saved_before_the_hold_is_kept_but_not_scheduled_or_approved(
    setup,
):
    client, version, directory = setup
    plan = version.plan
    current = joined(client, version)
    preview = simulate(client, plan, current, [patch(plan)]).json()["previews"][0]
    assert preview["simulation"]["status"] == "feasible"
    hold_spare(directory, plan.project_id)
    before = rows(directory)

    scheduled = preview_fabrication(client, plan.project_id, preview["preview_id"])
    assert (scheduled.status_code, scheduled.json()["code"]) == (409, "blocked")
    approved = commit(client, plan, current, preview["preview_id"])
    assert (approved.status_code, approved.json()["code"]) == (409, "blocked")
    assert rows(directory) == before
    assert active(client, plan.project_id) == plan.version_id

    # Once reconciled, the same saved preview can be scheduled and approved.
    correct_spare(client, plan.project_id)
    assert (
        preview_fabrication(client, plan.project_id, preview["preview_id"]).status_code
        == 200
    )
    approved = commit(client, plan, current, preview["preview_id"], key="commit-002")
    assert approved.status_code == 200, approved.text
    assert active(client, plan.project_id) == preview["version"]["version_id"]


def test_an_exact_replay_of_an_earlier_approval_is_still_returned(setup):
    # A replay returns an outcome already recorded before the hold.
    client, version, directory = setup
    plan = version.plan
    current = joined(client, version)
    preview = simulate(client, plan, current, [patch(plan)]).json()["previews"][0]
    first = commit(client, plan, current, preview["preview_id"])
    assert first.status_code == 200, first.text
    hold_spare(directory, plan.project_id)
    again = commit(client, plan, current, preview["preview_id"])
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert {**again.json(), "replayed": False} == first.json()


def test_muse_repair_advice_is_refused_while_held_without_a_provider_call(
    client_and_dir, monkeypatch
):
    client, directory = client_and_dir
    project, version = test_repair_route.active_project(client, directory)
    fake = test_repair_route.Fake(
        test_repair_route.final(
            candidates=[test_repair_route.resize_candidate(version.plan)]
        )
    )
    counter = test_repair_route.install(monkeypatch, fake)
    hold_spare(directory, project["id"])
    refused = test_repair_route.call(
        client, project, test_repair_route.body(project, version)
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "blocked")
    assert counter["factory"] == 0 and fake.calls == []


@pytest.fixture
def client_and_dir(tmp_path):
    from fastapi.testclient import TestClient
    from test_plans import TOKENS

    from forma_api.main import create_app

    with TestClient(create_app(tmp_path, TOKENS)) as client:
        yield client, tmp_path


def test_a_correction_saved_during_compilation_makes_that_compile_stale(
    client_and_dir,
):
    # Compilation reads the inventory revision when it starts. A correction
    # that withdraws confirmation issues a new revision, so a compile still
    # carrying the earlier revision is refused instead of being accepted.
    client, directory = client_and_dir
    project, body, context = prepared(client)
    sheet = project["stocks"][0]
    first = client.put(
        f"/api/projects/{project['id']}/recognized-items",
        headers=AUTH,
        json={
            "expected_revision": None,
            "idempotency_key": "items-compile-1",
            "items": [item(sheet["id"], "corrugated_cardboard")],
        },
    )
    assert first.status_code == 200, first.text
    started = client.get(f"/api/projects/{project['id']}", headers=AUTH).json()
    assert started["inventory_confirmed"] is True
    body = body.model_copy(update={"expected_revision_id": started["revision_id"]})
    contradicted = client.put(
        f"/api/projects/{project['id']}/recognized-items",
        headers=AUTH,
        json={
            "expected_revision": first.json()["revision"],
            "idempotency_key": "items-compile-2",
            "items": [item(sheet["id"], "plastic_bottle")],
        },
    )
    assert contradicted.status_code == 200, contradicted.text
    assert contradicted.json()["inventory_confirmed"] is False
    service = PlanService(ProjectStore(directory), allow_synthetic=True)
    with pytest.raises(ProjectError) as stale:
        service.compile_preview("alice", project["id"], body, **context)
    assert stale.value.envelope.code == "stale_version"
