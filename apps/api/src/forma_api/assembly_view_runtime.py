"""Adapt an authorized immutable snapshot without invoking physical analysis."""

import hashlib
import json

from forma_stability.geometry import UnsupportedGeometry

from forma_api.stability_geometry import preview_geometry
from forma_api.stability_runtime import StabilitySnapshot
from forma_domain.assembly_view_contracts import (
    AssemblyOperationParts,
    AssemblyViewResponse,
)


def assembly_view(snapshot: StabilitySnapshot) -> AssemblyViewResponse:
    evidence = {
        "evidence": [
            item.model_dump(mode="json") for item in snapshot.history_evidence
        ],
        "invalidations": [
            item.model_dump(mode="json") for item in snapshot.evidence_invalidations
        ],
        "measurements": snapshot.measurements.model_dump(mode="json")
        if snapshot.measurements
        else None,
    }
    revision = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    fields = dict(
        project_id=snapshot.project.id,
        plan_version_id=snapshot.version.version_id,
        inventory_revision_id=snapshot.project.revision_id,
        last_event_id=snapshot.last_event_id,
        evidence_revision=revision,
    )
    try:
        geometry = preview_geometry(snapshot)
    except UnsupportedGeometry as error:
        return AssemblyViewResponse(
            **fields, status="unsupported", operation_parts=(), blockers=(str(error),)
        )
    parts = set(geometry.active_part_ids)
    return AssemblyViewResponse(
        **fields,
        status="ready",
        geometry=geometry,
        operation_parts=tuple(
            AssemblyOperationParts(
                operation_id=operation.id,
                part_ids=tuple(part for part in operation.part_ids if part in parts),
            )
            for operation in snapshot.version.plan.operations
        ),
    )
