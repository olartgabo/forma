"""Connected synthetic display checks; no provider or physical success claims."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_plans import AUTH, OTHER
from test_progress import complete
from test_stability_runtime import authorized

from forma_api.assembly_view_runtime import assembly_view
from forma_api.stability_geometry import preview_geometry
from forma_domain.models import EvidenceInvalidation

pytest_plugins = ["test_stability_route"]


def test_evidence_revision_changes_when_evidence_is_invalidated(connected):
    snapshot = authorized(connected)
    before = assembly_view(snapshot)
    invalidation = EvidenceInvalidation(
        id="display-invalidation",
        evidence_id="historical-evidence",
        invalidated_for_version_id=snapshot.version.version_id,
        reason="Synthetic evidence invalidation; no physical observation",
        recorded_at=datetime.now(UTC),
    )
    after = assembly_view(replace(snapshot, evidence_invalidations=(invalidation,)))
    assert after.evidence_revision != before.evidence_revision
    assert after.geometry == before.geometry
    assert after.overlay_coverage == "unavailable"


def request(connected, **changes):
    client, url, payload, _ = connected
    params = payload | {"expected_last_event_id": ""} | changes
    project_id = url.split("/")[2]
    return client.get(
        f"/api/projects/{project_id}/assembly-view", headers=AUTH, params=params
    )


def test_exact_canonical_source_and_database_read_only(connected):
    _, _, _, directory = connected
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = request(connected)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["geometry"] == preview_geometry(authorized(connected)).model_dump(
        mode="json"
    )
    assert result["status"] == "ready"
    assert result["overlay_coverage"] == "unavailable"
    assert len(result["evidence_revision"]) == 64
    assert result["operation_parts"] == [
        {"operation_id": operation.id, "part_ids": list(operation.part_ids)}
        for operation in authorized(connected).version.plan.operations
    ]
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("plan_version_id", "foreign", 404),
        ("expected_inventory_revision_id", "stale", 409),
        ("expected_last_event_id", "stale", 409),
    ],
)
def test_stale_foreign_rejected(connected, field, value, status):
    assert request(connected, **{field: value}).status_code == status


def test_auth_scope_and_required_cursor(connected):
    client, url, payload, _ = connected
    path = f"/api/projects/{url.split('/')[2]}/assembly-view"
    params = payload | {"expected_last_event_id": ""}
    assert client.get(path, params=params).status_code == 401
    assert client.get(path, params=params, headers=OTHER).status_code == 404
    params.pop("expected_last_event_id")
    assert client.get(path, params=params, headers=AUTH).status_code == 422


def test_intermediate_falls_back_and_reported_assembly_remains_nominal(connected):
    client, _, _, _ = connected
    snap = authorized(connected)
    current = complete(client, snap.version, 0)
    assert request(connected).status_code == 409
    partial = request(connected, expected_last_event_id=current["last_event_id"]).json()
    assert partial["status"] == "unsupported"
    assert partial["geometry"] is None
    for index, operation in enumerate(snap.version.plan.operations):
        if index == 0:
            continue
        if operation.type == "functional_test":
            break
        current = complete(client, snap.version, index)
    full = request(connected, expected_last_event_id=current["last_event_id"]).json()
    assert full["status"] == "ready"
    assert full["geometry"]["stage"] == "reported_assembled"
    assert full["geometry"]["state_basis"] == "nominal"


def test_each_operation_has_separate_planned_illustration(connected):
    plan = authorized(connected).version.plan
    present, joints = set(), set()
    for operation in plan.operations:
        present.update(operation.effects.created_part_ids)
        joints.difference_update(operation.effects.detached_joint_ids)
        joints.update(operation.effects.attached_joint_ids)
        response = request(connected, selected_operation_id=operation.id)
        assert response.status_code == 200, response.text
        illustration = response.json()["planned_illustration"]
        assert illustration["operation_id"] == operation.id
        assert set(illustration["present_part_ids"]) == present
        assert set(illustration["planned_joint_ids"]) == joints
        assert {f["part_id"] for f in illustration["facets"]} == present
        assert "not actual positions" in illustration["notes"][0]
    assert request(connected, selected_operation_id="foreign").status_code == 422


def test_planned_reference_does_not_replace_unsupported_physical_state(connected):
    snap = authorized(connected)
    operation = snap.version.plan.operations[0]
    damaged = replace(
        snap,
        progress=snap.progress.model_copy(update={"damaged_part_ids": ("conflict",)}),
    )
    result = assembly_view(damaged, operation.id)
    assert result.status == "unsupported"
    assert result.geometry is None
    assert result.overlay_coverage == "unavailable"
    assert result.planned_illustration is not None
    assert any("flat" in n for n in result.planned_illustration.notes)


@pytest.mark.parametrize(
    "field", ["failed_operation_ids", "damaged_part_ids", "carried_operation_ids"]
)
def test_conflicting_physical_state_never_draws_final_joints(connected, field):
    snap = authorized(connected)
    result = assembly_view(
        replace(snap, progress=snap.progress.model_copy(update={field: ("conflict",)}))
    )
    assert result.status == "unsupported"
    assert result.geometry is None
    assert result.blockers
