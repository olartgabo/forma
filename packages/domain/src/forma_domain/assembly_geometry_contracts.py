"""Shared nominal assembly geometry; no observed pose or mass is inferred."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ID, Record, Text
from .stability_contracts import Point3


class CanonicalFacet(Record):
    facet_id: ID
    part_id: ID
    feature_id: ID | None = None
    vertices: tuple[Point3, ...] = Field(min_length=4, max_length=4)
    centroid: Point3
    area_fraction: Annotated[float, Field(gt=0, le=1)]


class PartCentroid(Record):
    part_id: ID
    centroid: Point3


class CanonicalGeometryPreview(Record):
    project_id: ID
    plan_version_id: ID
    producer_version: Text
    geometry_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    history_cursor: ID | None
    stage: Literal["planned_preview", "reported_assembled"]
    state_basis: Literal["nominal"] = "nominal"
    coordinate_frame: Literal["x_across_y_rearward_z_up_m"] = (
        "x_across_y_rearward_z_up_m"
    )
    active_part_ids: tuple[ID, ...] = Field(min_length=1, max_length=16)
    nominal_joint_ids: tuple[ID, ...] = Field(max_length=16)
    attached_joint_ids: tuple[ID, ...] = Field(max_length=16)
    completed_operation_ids: tuple[ID, ...] = Field(max_length=64)
    facets: tuple[CanonicalFacet, ...] = Field(min_length=1, max_length=32)
    part_centroids: tuple[PartCentroid, ...] = Field(min_length=1, max_length=16)
    ground_part_id: ID
    ground_polygon: tuple[Point3, ...] = Field(min_length=4, max_length=4)
    assumption_ids: tuple[ID, ...] = Field(min_length=1, max_length=16)
    assumptions: tuple[Text, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def coherent_parts_and_state(self):
        parts = set(self.active_part_ids)
        centroids = [item.part_id for item in self.part_centroids]
        if len(parts) != len(self.active_part_ids) or set(centroids) != parts:
            raise ValueError("Geometry requires exactly its active part centroids")
        if len(centroids) != len(parts) or self.ground_part_id not in parts:
            raise ValueError("Duplicate centroid or unknown ground part")
        if len({f.facet_id for f in self.facets}) != len(self.facets):
            raise ValueError("Facet IDs must be unique")
        if {f.part_id for f in self.facets} != parts:
            raise ValueError("Facets must cover exactly the active source parts")
        for part_id in parts:
            total = sum(f.area_fraction for f in self.facets if f.part_id == part_id)
            if abs(total - 1) > 1e-12:
                raise ValueError("Facet fractions must conserve each source part")
        for ids in (
            self.nominal_joint_ids,
            self.attached_joint_ids,
            self.completed_operation_ids,
            self.assumption_ids,
        ):
            if len(set(ids)) != len(ids):
                raise ValueError("Geometry identity lists cannot contain duplicates")
        if not set(self.attached_joint_ids) <= set(self.nominal_joint_ids):
            raise ValueError("Reported joints must belong to the nominal assembly")
        if self.stage == "planned_preview" and (
            self.attached_joint_ids or self.completed_operation_ids
        ):
            raise ValueError("Planned preview cannot claim completed assembly work")
        if self.stage == "reported_assembled" and (
            not self.completed_operation_ids
            or set(self.attached_joint_ids) != set(self.nominal_joint_ids)
        ):
            raise ValueError("Reported assembly requires completed work and joints")
        if any(point.z != 0 for point in self.ground_polygon):
            raise ValueError("Nominal ground must lie in the z=0 plane")
        return self
