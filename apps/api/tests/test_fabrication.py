"""Synthetic fabrication reports over saved plans; no physical attempt or pass."""

import sqlite3

import pytest
import test_adapt
from test_adapt import active, commit, joined, patch, progress, report, simulate
from test_plans import AUTH, OTHER

from forma_api import fabrication_runtime
from forma_api.adapt import RepairBase, confirmed_remaining
from forma_api.fabrication_runtime import FabricationAssessment
from forma_api.plans import PlanVersion
from forma_api.projects import Project, ProjectError, ProjectStore
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


def assessment(client, version, *, headers=AUTH, **changes):
    project = client.get(f"/api/projects/{version.project_id}", headers=AUTH).json()
    current = progress(client, version.project_id, version.version_id)
    return client.post(
        f"/api/projects/{version.project_id}/versions/{version.version_id}/fabrication/assess",
        headers=headers,
        json={
            "expected_inventory_revision_id": project["revision_id"],
            "expected_last_event_id": current["last_event_id"],
            **changes,
        },
    )


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
    assert body["status"] == "blocked"
    assert body["next_operation_id"] is None
    cut = by_id(body)["stand-cut-panels"]
    assert cut["next_state_id"] is None
    assert cut["status"] == "blocked"
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


def test_additional_tool_confirmation_is_explicit_read_only_and_withdrawable(setup):
    client, version, directory = setup
    original = fabrication(client, version.project_id, version.version_id).json()
    before = rows(directory)
    assert assessment(client, version, headers={}).status_code == 401
    assert assessment(client, version, headers=OTHER).status_code == 404
    for changes in (
        {"additional_tools": ["scissors"]},
        {"additional_tools": ["scissors"], "tools_confirmed": 1},
        {"additional_tools": ["scissors", " SCISSORS "], "tools_confirmed": True},
        {"additional_tools": [], "tools_confirmed": True},
        {"completed_operation_ids": ["stand-cut-panels"]},
    ):
        response = assessment(client, version, **changes)
        assert response.status_code == 422, response.text
    response = assessment(
        client, version, additional_tools=["scissors"], tools_confirmed=True
    )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["next_operation_id"] == "stand-cut-panels"
    assert body["current_state_id"] == original["current_state_id"]
    assert body["snapshot"]["inputs_sha256"] != original["snapshot"]["inputs_sha256"]
    assert rows(directory) == before
    assert (
        fabrication(client, version.project_id, version.version_id).json() == original
    )
    assert (
        assessment(
            client, version, expected_inventory_revision_id="old-inventory"
        ).status_code
        == 409
    )
    assert (
        assessment(client, version, expected_last_event_id="old-history").status_code
        == 409
    )


def test_fresh_measured_lengths_are_required_and_cannot_rewrite_the_ledger(setup):
    client, version, directory = setup
    for operation in version.plan.operations[:4]:
        current = report(client, version.project_id, version.plan, operation.id)
    response = fabrication(client, version.project_id, version.version_id)
    original = response.json()
    assert original["required_connector_measurement_ids"] == ["synthetic-tape-stock"]
    joins = [
        item
        for item in original["operations"]
        if item["operation_type"] == "tape_joint" and item["status"] != "completed"
    ]
    assert joins and all(
        any(b["code"] == "missing_measurement" for b in item["blockers"])
        for item in joins
    )
    value = next(
        stock["remaining_length_mm"]["value"]
        for stock in current["expected_remaining_stock"]
        if stock["kind"] == "tape"
    )
    measured = [{"stock_id": "synthetic-tape-stock", "remaining_length_mm": value}]
    for changes in (
        {"connector_measurements": measured},
        {"connector_measurements": measured, "remaining_confirmed": 1},
        {"connector_measurements": measured * 2, "remaining_confirmed": True},
        {
            "connector_measurements": [
                {"stock_id": "foreign-stock", "remaining_length_mm": value}
            ],
            "remaining_confirmed": True,
        },
        {
            "connector_measurements": [
                {"stock_id": "synthetic-tape-stock", "remaining_length_mm": value - 1}
            ],
            "remaining_confirmed": True,
        },
        {
            "connector_measurements": [
                {"stock_id": "synthetic-tape-stock", "remaining_length_mm": value + 1}
            ],
            "remaining_confirmed": True,
        },
    ):
        rejected = assessment(client, version, **changes)
        assert rejected.status_code == 422, rejected.text
    before = rows(directory)
    response = assessment(
        client,
        version,
        connector_measurements=measured,
        remaining_confirmed=True,
        additional_tools=["scissors"],
        tools_confirmed=True,
    )
    assert response.status_code == 200, response.text
    checked = response.json()
    assert checked["next_operation_id"] == "stand-joint-rear-attach", checked
    assert checked["required_connector_measurement_ids"] == []
    assert checked["snapshot"]["inputs_sha256"] != original["snapshot"]["inputs_sha256"]
    assert rows(directory) == before
    assert progress(client, version.project_id, version.version_id) == current
    assert (
        fabrication(client, version.project_id, version.version_id).json() == original
    )
    report(client, version.project_id, version.plan, "stand-joint-rear-attach")
    stale = assessment(
        client,
        version,
        expected_last_event_id=current["last_event_id"],
        connector_measurements=measured,
        remaining_confirmed=True,
    )
    assert stale.status_code == 409


def test_report_subset_does_not_confirm_an_unused_connector(setup):
    client, version, directory = setup
    for operation in version.plan.operations[:4]:
        current = report(client, version.project_id, version.plan, operation.id)
    with ProjectStore(directory).transaction() as connection:
        base = RepairBase(connection, version.project_id, version.version_id)
    spent = next(
        stock
        for stock in base.progress.expected_remaining_stock
        if stock.kind == "tape"
    )
    unused = spent.model_copy(update={"id": "spent-unused-tape"})
    # Exercise two connector balances at the existing adapter boundary, without
    # claiming the current renderer generates two-connector stands.
    base.progress = base.progress.model_copy(
        update={
            "expected_remaining_stock": base.progress.expected_remaining_stock
            + (unused,)
        }
    )
    body = FabricationAssessment(
        expected_inventory_revision_id=version.inventory_revision_id,
        expected_last_event_id=current["last_event_id"],
        connector_measurements=(
            {
                "stock_id": spent.id,
                "remaining_length_mm": spent.remaining_length_mm.value,
            },
        ),
        remaining_confirmed=True,
    )
    with pytest.raises(ProjectError):
        confirmed_remaining(base, body.connector_measurements)
    stocks = {
        stock.id: stock
        for stock in confirmed_remaining(
            base, body.connector_measurements, require_all=False
        )
    }
    assert stocks[spent.id].remaining_length_mm.confirmed
    assert stocks[unused.id] == unused
    assert not stocks[unused.id].remaining_length_mm.confirmed


def test_report_assessment_accepts_more_than_eight_connector_measurements(setup):
    client, version, directory = setup
    for operation in version.plan.operations[:4]:
        current = report(client, version.project_id, version.plan, operation.id)
    with ProjectStore(directory).transaction() as connection:
        base = RepairBase(connection, version.project_id, version.version_id)
    spent = next(
        stock
        for stock in base.progress.expected_remaining_stock
        if stock.kind == "tape"
    )
    # Validate the bounded request/adapter contract for nine calculated
    # balances. This does not claim the renderer generates nine-tape stands.
    connectors = (spent,) + tuple(
        spent.model_copy(update={"id": f"spent-tape-{i}"}) for i in range(8)
    )
    base.progress = base.progress.model_copy(
        update={"expected_remaining_stock": connectors}
    )
    values = dict(
        expected_inventory_revision_id=version.inventory_revision_id,
        expected_last_event_id=current["last_event_id"],
        connector_measurements=tuple(
            {
                "stock_id": stock.id,
                "remaining_length_mm": stock.remaining_length_mm.value,
            }
            for stock in connectors
        ),
        remaining_confirmed=True,
    )
    body = FabricationAssessment(**values)
    measured = confirmed_remaining(base, body.connector_measurements, require_all=False)
    assert len(measured) == 9 and all(
        stock.remaining_length_mm.confirmed for stock in measured
    )
    with pytest.raises(ValueError):
        FabricationAssessment(
            **{
                **values,
                "connector_measurements": tuple(
                    {"stock_id": f"tape-{i}", "remaining_length_mm": 1}
                    for i in range(33)
                ),
            }
        )


def test_history_above_report_bound_returns_explicit_conflict_not_500(setup):
    client, version, directory = setup
    with sqlite3.connect(directory / "projects.sqlite3") as connection:
        row = connection.execute(
            "SELECT body, process, parameters FROM plans WHERE version_id=?",
            (version.version_id,),
        ).fetchone()
        saved = PlanVersion.model_validate_json(row[0])
        parent = version.version_id
        for i in range(32):
            current_id = f"history-version-{i}"
            child = saved.model_copy(
                update={
                    "version_id": current_id,
                    "plan": saved.plan.model_copy(
                        update={"version_id": current_id, "parent_version_id": parent}
                    ),
                    "manual": saved.manual.model_copy(
                        update={"version_id": current_id}
                    ),
                }
            )
            connection.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                (
                    current_id,
                    version.project_id,
                    version.inventory_revision_id,
                    child.model_dump_json(),
                    row[1],
                    row[2],
                ),
            )
            parent = current_id
        project_body = connection.execute(
            "SELECT body FROM projects WHERE id=?", (version.project_id,)
        ).fetchone()[0]
        project = Project.model_validate_json(project_body).model_copy(
            update={"active_version_id": parent}
        )
        connection.execute(
            "UPDATE projects SET body=? WHERE id=?",
            (project.model_dump_json(), project.id),
        )
    before = rows(directory)
    result = fabrication(client, version.project_id, parent)
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "blocked"
    assert "32 plan versions" in result.json()["message"]
    assert rows(directory) == before


def test_proposed_history_limit_is_checked_before_building_report_input(setup):
    client, version, _ = setup
    project = Project.model_validate(
        client.get(f"/api/projects/{version.project_id}", headers=AUTH).json()
    )
    # The report boundary must include a proposed preview in its version bound.
    # Oversized lineage is refused before Pydantic input construction can raise.
    with pytest.raises(ProjectError) as error:
        fabrication_runtime._report(project, (None,) * 33, (), None, None, version.plan)
    assert error.value.status == 409
    assert error.value.envelope.code == "blocked"
    assert "including a proposed revision" in error.value.envelope.message
