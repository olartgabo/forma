"""Default canonical plan path; synthetic software inputs, no physical evidence."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_plans import AUTH
from test_progress import complete
from test_stability_runtime import authorized

from forma_api import stability_runtime as runtime
from forma_domain.models import EvidenceInvalidation, PhysicalEvent

pytest_plugins = ["test_stability_route"]


def test_default_preview_is_same_plan_deterministic_and_not_a_report(connected):
    client, url, body, _ = connected
    first = client.post(url, headers=AUTH, json=body)
    second = client.post(url, headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    result = first.json()
    geometry = result["geometry_preview"]
    snap = authorized(connected)
    assert geometry["project_id"] == snap.project.id
    assert geometry["plan_version_id"] == snap.version.version_id
    assert geometry["history_cursor"] is None
    assert geometry["state_basis"] == "nominal"
    assert geometry["stage"] == "planned_preview"
    assert set(geometry["active_part_ids"]) == {p.id for p in snap.version.plan.parts}
    assert {facet["part_id"] for facet in geometry["facets"]} == set(
        geometry["active_part_ids"]
    )
    assert len(geometry["geometry_hash"]) == 64
    assert result["status"] == "needs_measurement"
    assert result["report"] is None
    assert any("mass" in blocker for blocker in result["blockers"])
    assert any("policy" in blocker for blocker in result["blockers"])
    assert any("contact" in blocker for blocker in result["blockers"])
    assert geometry["assumption_ids"]


def test_partial_construction_is_not_presented_as_complete(connected):
    client, url, body, _ = connected
    snap = authorized(connected)
    current = complete(client, snap.version, 0)
    response = client.post(
        url,
        headers=AUTH,
        json=body | {"expected_last_event_id": current["last_event_id"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "unsupported"
    assert result["geometry_preview"] is None
    assert result["report"] is None
    assert result["blockers"]


def test_reported_assembly_still_requires_measurements_and_policy(connected):
    client, url, body, _ = connected
    snap = authorized(connected)
    for index, operation in enumerate(snap.version.plan.operations):
        if operation.type == "functional_test":
            break
        current = complete(client, snap.version, index)
    response = client.post(
        url,
        headers=AUTH,
        json=body | {"expected_last_event_id": current["last_event_id"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "needs_measurement"
    assert result["report"] is None
    geometry = result["geometry_preview"]
    assert geometry["stage"] == "reported_assembled"
    assert geometry["state_basis"] == "nominal"
    assert geometry["history_cursor"] == current["last_event_id"]


@pytest.mark.parametrize(
    "field", ["failed_operation_ids", "damaged_part_ids", "carried_operation_ids"]
)
def test_progress_conflicts_reject_default_geometry(connected, field):
    snap = authorized(connected)
    snap = replace(
        snap, progress=snap.progress.model_copy(update={field: ("conflict",)})
    )
    result = runtime.analyze(snap)
    assert result.status == "unsupported"
    assert result.geometry_preview is None
    assert result.report is None


def test_mismatched_snapshot_identity_rejected(connected):
    snap = authorized(connected)
    with pytest.raises(ValueError, match="identity"):
        runtime.analyze(replace(snap, last_event_id="unrecorded-history"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "foreign"),
        ("plan_version_id", "foreign"),
        ("last_event_id", "stale"),
    ],
)
def test_preview_cannot_be_wrapped_in_another_response_context(connected, field, value):
    result = runtime.analyze(authorized(connected))
    with pytest.raises(ValueError, match="identity"):
        runtime.StabilityAnalysisResponse.model_validate(
            result.model_dump() | {field: value}
        )


def test_preview_cannot_claim_complete(connected):
    result = runtime.analyze(authorized(connected))
    with pytest.raises(ValueError, match="cannot establish"):
        runtime.StabilityAnalysisResponse.model_validate(
            result.model_dump() | {"status": "complete"}
        )


def test_invalidated_reported_assembly_is_not_reused(connected):
    client, _, _, _ = connected
    snap = authorized(connected)
    for index, operation in enumerate(snap.version.plan.operations):
        if operation.type == "functional_test":
            break
        current = complete(client, snap.version, index)
    events = tuple(PhysicalEvent.model_validate(event) for event in current["events"])
    snap = replace(
        snap,
        last_event_id=current["last_event_id"],
        history_events=events,
        evidence_invalidations=(
            EvidenceInvalidation(
                id="invalidated-construction",
                evidence_id="historical-construction",
                invalidated_for_version_id=snap.version.version_id,
                reason="Synthetic invalidation regression",
                recorded_at=datetime.now(UTC),
            ),
        ),
    )
    result = runtime.analyze(snap)
    assert result.status == "unsupported"
    assert "Invalidated" in result.blockers[0]
    assert result.geometry_preview is None
    assert result.report is None
