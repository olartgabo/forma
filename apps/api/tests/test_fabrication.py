"""Synthetic fabrication reports over saved plans; no physical attempt or pass."""

import sqlite3

import pytest
import test_adapt
from test_adapt import active, commit, joined, patch, progress, report, simulate
from test_plans import AUTH, OTHER

from forma_api import fabrication_runtime
from forma_domain.models import BuildPlan

repair_setup = test_adapt.setup

TABLES = (
    "projects",
    "plans",
    "progress_events",
    "progress_evidence",
    "progress_material",
    "adapt_previews",
    "plan_revisions",
    "evidence_invalidations",
    "requests",
)


@pytest.fixture
def setup(repair_setup, monkeypatch):
    monkeypatch.setattr(fabrication_runtime, "ALLOW_SYNTHETIC", True)
    return repair_setup


def fabrication(client, project_id, version_id, headers=AUTH):
    return client.get(
        f"/api/projects/{project_id}/versions/{version_id}/fabrication",
        headers=headers,
    )


def preview_fabrication(client, project_id, preview_id, headers=AUTH):
    return client.get(
        f"/api/projects/{project_id}/adapt/previews/{preview_id}/fabrication",
        headers=headers,
    )


def rows(directory):
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }


def by_id(body):
    return {item["operation_id"]: item for item in body["operations"]}


def test_scope_and_stale_version_are_checked_first(setup):
    client, version, _ = setup
    pid, vid = version.project_id, version.version_id
    assert fabrication(client, pid, vid, {}).status_code == 401
    foreign = fabrication(client, pid, vid, OTHER)
    assert foreign.status_code == 404
    assert vid not in foreign.text
    assert fabrication(client, "missing-project", vid).status_code == 404
    stale = fabrication(client, pid, "not-the-active-version")
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_version"
    assert preview_fabrication(client, pid, "missing-preview").status_code == 404


def test_report_reads_saved_state_and_names_the_missing_cutting_tool(setup):
    client, version, directory = setup
    before = rows(directory)
    response = fabrication(client, version.project_id, version.version_id)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert rows(directory) == before
    project = client.get(f"/api/projects/{version.project_id}", headers=AUTH).json()
    assert body["snapshot"]["version_id"] == version.version_id
    assert body["snapshot"]["inventory_revision_id"] == project["revision_id"]
    assert body["snapshot"]["last_event_id"] is None
    assert body["status"] == "ready"
    assert body["next_operation_id"] == "stand-cut-panels"
    cut = by_id(body)["stand-cut-panels"]
    assert cut["next_state_id"].startswith("state-")
    # The saved tools list only "Synthetic ruler".
    assert {t["tool"]: t["status"] for t in cut["tools"]} == {
        "cutting_tool": "not_declared",
        "ruler": "declared",
    }
    assert any(
        "None of your saved tools is a cutting tool" in c
        for c in cut["required_confirmations"]
    )
    assert body["observed_usability"] == "not_assessed"
    assert "image_ids" not in response.text


def test_report_follows_recorded_history(setup):
    client, version, _ = setup
    current = joined(client, version)
    body = fabrication(client, version.project_id, version.version_id).json()
    assert body["snapshot"]["last_event_id"] == current["last_event_id"]
    assert body["attached_joint_ids"] == [
        "stand-joint-apex",
        "stand-joint-front",
        "stand-joint-rear",
    ]
    statuses = {o["operation_id"]: o["status"] for o in body["operations"]}
    assert [statuses[o.id] for o in version.plan.operations[:6]] == ["completed"] * 6
    assert body["supported_order"][0]["operation_id"] == "stand-inspect-fit"


def test_repair_preview_report_schedules_the_peel_without_approving(setup):
    client, version, directory = setup
    plan = version.plan
    current = joined(client, version)
    preview = simulate(client, plan, current, [patch(plan)]).json()["previews"][0]
    before = rows(directory)
    response = preview_fabrication(client, plan.project_id, preview["preview_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert rows(directory) == before
    assert active(client, plan.project_id) == plan.version_id
    assert progress(client, plan.project_id, plan.version_id) == current
    assert body["snapshot"]["version_id"] == preview["version"]["version_id"]
    peels = preview["simulation"]["required_undo_operation_ids"]
    assert body["supported_order"][0]["operation_id"] == peels[0]
    assert by_id(body)["stand-joint-rear-attach"]["status"] == "completed"
    assert body["attached_joint_ids"] == [
        "stand-joint-apex",
        "stand-joint-front",
        "stand-joint-rear",
    ]

    # New history makes the saved preview stale for scheduling too.
    report(client, plan.project_id, plan, "stand-inspect-fit")
    stale = preview_fabrication(client, plan.project_id, preview["preview_id"])
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_version"


def test_approved_revision_report_replays_the_peel(setup):
    client, version, _ = setup
    plan = version.plan
    current = joined(client, version)
    preview = simulate(client, plan, current, [patch(plan)]).json()["previews"][0]
    approved = commit(client, plan, current, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    new_id = approved.json()["revision"]["version_id"]
    revised = BuildPlan.model_validate(preview["version"]["plan"])
    peel = preview["simulation"]["required_undo_operation_ids"][0]
    before = fabrication(client, plan.project_id, new_id).json()
    assert before["next_operation_id"] == peel
    assert fabrication(client, plan.project_id, plan.version_id).status_code == 409
    report(client, plan.project_id, revised, peel)
    after = fabrication(client, plan.project_id, new_id).json()
    assert by_id(after)["stand-joint-rear-attach"]["status"] == "completed"
    assert "stand-joint-rear" not in after["attached_joint_ids"]
    assert by_id(after)[peel]["completed_in_version_id"] == new_id


def test_production_default_rejects_synthetic_profile_evidence(setup, monkeypatch):
    client, version, _ = setup
    monkeypatch.setattr(fabrication_runtime, "ALLOW_SYNTHETIC", False)
    body = fabrication(client, version.project_id, version.version_id).json()
    assert body["status"] == "blocked"
    assert any(b["code"] == "unsupported_profile" for b in body["blockers"])
    assert body["supported_order"] == []
