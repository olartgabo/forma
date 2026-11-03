"""Resolve shared canonical geometry without inventing mechanical measurements."""

from typing import TYPE_CHECKING

from forma_stability.geometry import UnsupportedGeometry, project_nominal_geometry

if TYPE_CHECKING:
    from forma_api.stability_runtime import StabilitySnapshot


def preview_geometry(snapshot: "StabilitySnapshot"):
    """Return nominal plan geometry, never a physical or mechanical pass.

    The route loads the complete project history in insertion order. Passing that
    history through preserves the producer's rejection of unsupported previous
    versions and detach/repair states instead of hiding them by filtering.
    """
    if (
        snapshot.version.project_id != snapshot.project.id
        or snapshot.version.plan.project_id != snapshot.project.id
        or snapshot.version.version_id != snapshot.version.plan.version_id
        or snapshot.project.active_version_id != snapshot.version.version_id
        or snapshot.last_event_id
        != (snapshot.history_events[-1].id if snapshot.history_events else None)
    ):
        raise ValueError("Geometry snapshot identity does not match authorized state")
    if (
        snapshot.progress.failed_operation_ids
        or snapshot.progress.damaged_part_ids
        or snapshot.progress.carried_operation_ids
    ):
        raise UnsupportedGeometry(
            "Failed, damaged or carried construction requires a supported geometry continuation"
        )
    geometry = project_nominal_geometry(
        snapshot.version.plan, history_events=snapshot.history_events
    )
    construction_evidence = {
        evidence_id
        for event in snapshot.history_events
        if event.kind in ("operation_confirmed", "damage", "test")
        for evidence_id in event.evidence_ids
    }
    # Only server-stored typed batches are numerical inputs, not construction
    # evidence. Their invalidation blocks that batch but permits recapture.
    numerical_evidence = set(snapshot.measurement_evidence_ids) - construction_evidence
    if geometry.stage == "reported_assembled" and any(
        item.invalidated_for_version_id == snapshot.version.version_id
        and item.evidence_id not in numerical_evidence
        for item in snapshot.evidence_invalidations
    ):
        raise UnsupportedGeometry(
            "Invalidated construction evidence must be reconciled before using reported assembly geometry"
        )
    return geometry


def missing_mechanical_inputs(part_ids: tuple[str, ...]) -> tuple[str, ...]:
    return (
        "Measure assembled stand mass and world center of mass including all parts ("
        + ", ".join(part_ids)
        + ") and all connectors together; do not count folded facets twice",
        "Bind device mass, world-space center of mass and device contact pose to typed measurement records",
        "Confirm actual supporting surface contacts; the preview footprint is nominal, not measured contact",
        "Supply explicit phone-orientation load cases, applicability assumptions and an analysis policy with a required physical margin",
    )
