"""Read-only assembly display envelopes; canonical physical geometry is unchanged."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assembly_geometry_contracts import CanonicalGeometryPreview
from .models import ID, Record, Text
from .stability_contracts import StabilityReport


class AssemblyOperationParts(Record):
    operation_id: ID
    part_ids: tuple[ID, ...] = Field(max_length=16)


class AssemblyViewResponse(Record):
    project_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    last_event_id: ID | None
    evidence_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["ready", "unsupported"]
    geometry: CanonicalGeometryPreview | None = None
    operation_parts: tuple[AssemblyOperationParts, ...] = Field(max_length=64)
    blockers: tuple[Text, ...] = ()
    overlay_coverage: Literal["unavailable", "available"] = "unavailable"
    overlay_report_id: ID | None = None
    overlay_report: StabilityReport | None = None

    @model_validator(mode="after")
    def coherent_display(self):
        geometry = self.geometry
        if (self.status == "ready") != (geometry is not None):
            raise ValueError("Only ready views contain geometry")
        if geometry is not None and (
            geometry.project_id != self.project_id
            or geometry.plan_version_id != self.plan_version_id
            or geometry.history_cursor != self.last_event_id
        ):
            raise ValueError("Geometry must match display snapshot")
        if len({item.operation_id for item in self.operation_parts}) != len(
            self.operation_parts
        ):
            raise ValueError("Operation links must be unique")
        if geometry is not None and any(
            not set(item.part_ids) <= set(geometry.active_part_ids)
            for item in self.operation_parts
        ):
            raise ValueError("Operation links reference unknown display parts")
        report = self.overlay_report
        if (self.overlay_coverage == "available") != (report is not None):
            raise ValueError("Available overlays require a saved report")
        if report is None:
            if self.overlay_report_id is not None:
                raise ValueError("Missing overlay report cannot have an identity")
        elif (
            geometry is None
            or self.overlay_report_id != "stability-report-" + report.cache_hash
            or report.identity.project_id != self.project_id
            or report.identity.plan_version_id != self.plan_version_id
            or report.identity.inventory_revision != self.inventory_revision_id
            or report.identity.history_cursor != self.last_event_id
            or report.identity.canonical_geometry_hash != geometry.geometry_hash
            or report.geometry_version != geometry.producer_version
            or not report.overlays
            or any(
                not any(
                    result.case_id == overlay.case_id
                    and result.check_type == "tip"
                    and result.computation == "complete"
                    for result in report.results
                )
                for overlay in report.overlays
            )
        ):
            raise ValueError("Saved overlay must match the exact canonical snapshot")
        return self
