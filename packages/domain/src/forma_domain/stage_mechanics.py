"""Explicit physical stage inputs, independent of display/camera transforms."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assembly_geometry_contracts import CanonicalFacet
from .models import ID, Record, Text
from .stability_contracts import (
    AnalysisPolicy,
    ContentHash,
    FiniteScalar,
    LoadCase,
    Point3,
    StabilityInput,
    StabilityReport,
)

Vector = tuple[FiniteScalar, FiniteScalar, FiniteScalar]


class RigidTransform(Record):
    """Right-handed local-to-world rotation and translation in metres."""

    rotation: tuple[Vector, Vector, Vector]
    translation_m: Point3

    @model_validator(mode="after")
    def orthonormal(self):
        r = self.rotation
        for i in range(3):
            for j in range(3):
                if abs(sum(r[i][k] * r[j][k] for k in range(3)) - (i == j)) > 1e-9:
                    raise ValueError("Rotation must be orthonormal")
        determinant = sum(
            r[0][i]
            * (
                r[1][(i + 1) % 3] * r[2][(i + 2) % 3]
                - r[1][(i + 2) % 3] * r[2][(i + 1) % 3]
            )
            for i in range(3)
        )
        if abs(determinant - 1) > 1e-9:
            raise ValueError("Rotation must preserve handedness")
        return self


class StageFacetPose(Record):
    facet_id: ID
    transform: RigidTransform


class StageContact(Record):
    contact_id: ID
    polygon_world: tuple[Point3, ...] = Field(min_length=3, max_length=128)


class StagePart(Record):
    part_id: ID
    mass_kg: Annotated[FiniteScalar, Field(gt=0)] | None
    center_of_mass_world: Point3 | None
    facet_poses: tuple[StageFacetPose, ...] = Field(max_length=32)
    contacts: tuple[StageContact, ...] = Field(max_length=16)
    rigid_body_assumed: bool


class StageSnapshot(Record):
    project_id: ID
    plan_version_id: ID
    inventory_revision: ID
    history_cursor: ID | None
    completed_operation_ids: tuple[ID, ...] = Field(max_length=64)
    basis: Literal["hypothetical", "observed"]
    support_frame: RigidTransform
    gravity_world_m_s2: Point3
    parts: tuple[StagePart, ...] = Field(max_length=16)
    rigid_joint_ids: tuple[ID, ...] = Field(max_length=32)
    assumption_notes: tuple[Text, ...] = Field(min_length=1, max_length=32)
    component_loads: tuple[LoadCase, ...] = Field(default=(), max_length=16)


class StageAnalysisResult(Record):
    producer_version: Text
    snapshot_hash: ContentHash
    snapshot: StageSnapshot
    present_part_ids: tuple[ID, ...]
    future_part_ids: tuple[ID, ...]
    active_joint_ids: tuple[ID, ...]
    facets: tuple[CanonicalFacet, ...]
    component_part_ids: tuple[tuple[ID, ...], ...]
    inputs: tuple[StabilityInput, ...]
    policies: tuple[AnalysisPolicy, ...]
    reports: tuple[StabilityReport, ...]
    blockers: tuple[Text, ...]
    physical_evidence_ids: tuple[ID, ...] = ()
