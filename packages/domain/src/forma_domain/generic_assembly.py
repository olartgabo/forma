"""Declarative polygonal assemblies and hypothetical physical stages.

Stages describe supplied physical membership, not fabrication permission or a
second operation scheduler. Numerical geometry validation belongs to the producer.
"""

from typing import Annotated

from pydantic import Field

from .models import ID, Record, Text
from .stability_contracts import (
    AnalysisPolicy,
    ContentHash,
    Point3,
    StabilityInput,
    StabilityOverlay,
    StabilityReport,
)
from .stage_mechanics import StageSnapshot


class AssemblyFacet(Record):
    facet_id: ID
    vertices_local: tuple[Point3, ...] = Field(min_length=3, max_length=64)


class FacetEdge(Record):
    facet_id: ID
    edge_index: Annotated[int, Field(strict=True, ge=0, le=63)]


class AssemblySeam(Record):
    first: FacetEdge
    second: FacetEdge


class AssemblyPart(Record):
    part_id: ID
    facets: tuple[AssemblyFacet, ...] = Field(min_length=1, max_length=32)
    seams: tuple[AssemblySeam, ...] = Field(default=(), max_length=64)


class AssemblyJoint(Record):
    joint_id: ID
    first: FacetEdge
    second: FacetEdge


class AssemblyStage(Record):
    stage_id: ID
    label: Text
    present_part_ids: tuple[ID, ...] = Field(max_length=16)
    active_joint_ids: tuple[ID, ...] = Field(max_length=32)


class GenericAssembly(Record):
    project_id: ID
    plan_version_id: ID
    parts: tuple[AssemblyPart, ...] = Field(min_length=1, max_length=16)
    joints: tuple[AssemblyJoint, ...] = Field(default=(), max_length=32)
    stages: tuple[AssemblyStage, ...] = Field(min_length=1, max_length=64)


class GenericAssemblyRequest(Record):
    assembly: GenericAssembly
    stage_id: ID
    snapshot: StageSnapshot
    policy: AnalysisPolicy
    uniform_mass_part_ids: tuple[ID, ...] = Field(default=(), max_length=16)
    full_face_contact_facet_ids: tuple[ID, ...] = Field(default=(), max_length=128)


class PolygonalFacet(Record):
    facet_id: ID
    part_id: ID
    vertices: tuple[Point3, ...] = Field(min_length=3, max_length=64)
    centroid: Point3
    area_fraction: Annotated[float, Field(gt=0, le=1)]


class GenericAssemblyResult(Record):
    producer_version: Text
    stage_id: ID
    stage_label: Text
    snapshot_hash: ContentHash
    request: GenericAssemblyRequest
    snapshot: StageSnapshot
    present_part_ids: tuple[ID, ...]
    future_part_ids: tuple[ID, ...]
    active_joint_ids: tuple[ID, ...]
    facets: tuple[PolygonalFacet, ...]
    component_part_ids: tuple[tuple[ID, ...], ...]
    inputs: tuple[StabilityInput, ...]
    policies: tuple[AnalysisPolicy, ...]
    reports: tuple[StabilityReport, ...]
    world_overlays: tuple[StabilityOverlay, ...]
    blockers: tuple[Text, ...]
    physical_evidence_ids: tuple[ID, ...] = ()
