"""Read-only construction proposals against owner-scoped saved materials.

This accepts typed targets and naming proposals from a caller, including a model
coordinator. It makes no provider call and grants no plan activation authority.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from forma_stability.construction import bind_operations, generate_construction
from forma_stability.construction_fabrication import build_fabrication
from pydantic import Field, StrictBool, model_validator

from forma_api import design_context
from forma_api.projects import ProjectError, ProjectStore
from forma_domain.construction_plan import ConstructionPlan, ConstructionRequest
from forma_domain.construction_resources import (
    ConstructionCutProcess,
    ConstructionJointMaterial,
    ConstructionResources,
)
from forma_domain.fabrication_contracts import FabricationReport
from forma_domain.generic_assembly import GenericAssemblyRequest
from forma_domain.models import ID, BuildPlan, Record, Text
from forma_domain.piece_references import PieceAnnotation


class ConstructionGenerateRequest(Record):
    expected_inventory_revision_id: ID
    target: GenericAssemblyRequest
    piece_annotations: tuple[PieceAnnotation, ...] = Field(default=(), max_length=16)
    joints: tuple[ConstructionJointMaterial, ...] = Field(default=(), max_length=32)
    joint_access_user_confirmed: StrictBool = False

    @model_validator(mode="after")
    def proposal_only(self):
        if (
            self.target.snapshot.basis != "hypothetical"
            or self.target.snapshot.completed_operation_ids
        ):
            raise ValueError("Construction targets cannot claim physical work")
        if (
            any(j.confirmed_accessible is not None for j in self.joints)
            and not self.joint_access_user_confirmed
        ):
            raise ValueError("Joint access claims require explicit user confirmation")
        if len({j.joint_id for j in self.joints}) != len(self.joints):
            raise ValueError("Duplicate joint material binding")
        return self


class ConstructionGenerateResult(Record):
    project_id: ID
    inventory_revision_id: ID
    context_fingerprint: str
    construction: ConstructionPlan
    fabrication_plan: BuildPlan | None
    fabrication_report: FabricationReport | None
    fabrication_blockers: tuple[Text, ...]


def _current(project, body):
    if project.revision_id != body.expected_inventory_revision_id:
        raise ProjectError(409, "stale_version", "Inventory changed; reload it")
    if project.active_version_id is not None:
        raise ProjectError(
            409,
            "blocked",
            "Existing builds require the history-aware fabrication and repair flow",
        )


def construction_router(
    store: ProjectStore, authenticate, context_resolver=None
) -> APIRouter:
    router = APIRouter(tags=["construction"])
    Owner = Annotated[str, Depends(authenticate)]

    @router.post(
        "/{project_id}/construction/generate", response_model=ConstructionGenerateResult
    )
    def generate(
        project_id: ID,
        body: ConstructionGenerateRequest,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
        _current(project, body)
        target = body.target
        if (
            target.assembly.project_id != project_id
            or target.snapshot.project_id != project_id
            or target.snapshot.inventory_revision != project.revision_id
        ):
            raise ProjectError(
                422,
                "validation_error",
                "Target must match the saved project and inventory revision",
            )
        resolver = context_resolver or design_context.default_context_resolver()
        resolved = resolver(project_id, project.revision_id)
        try:
            construction = generate_construction(
                ConstructionRequest(
                    target=target, piece_annotations=body.piece_annotations
                )
            )
            blockers = [b.message for b in resolved.blockers]
            if not project.inventory_confirmed or not project.stocks:
                blockers.append(
                    "Save and confirm your available inventory before assessing fabrication."
                )
            plan = report = None
            if not blockers:
                resources = ConstructionResources(
                    project_id=project_id,
                    inventory_revision_id=project.revision_id,
                    active_version_id=project.active_version_id,
                    stocks=project.stocks,
                    declared_tools=project.requirements.tools
                    if project.requirements
                    else None,
                    safe_tools_confirmed=resolved.parameters.tools_confirmed
                    if resolved.parameters
                    else False,
                    cut_process=ConstructionCutProcess.model_validate(
                        resolved.process.model_dump()
                    )
                    if resolved.process
                    else None,
                    joint_profiles=resolved.joint_profiles,
                    profile_evidence=resolved.parameters.profile_evidence
                    if resolved.parameters
                    else (),
                    joints=body.joints,
                )
                plan, report, bindings, messages = build_fabrication(
                    construction, resources=resources
                )
                blockers.extend(messages)
                if bindings:
                    construction = bind_operations(construction, bindings)
        except ValueError:
            # Geometry/schema errors may contain user labels; never return a raw
            # traceback or server context/evidence in an exception response.
            raise ProjectError(
                422,
                "validation_error",
                "Construction proposal or configured material context is invalid",
            ) from None
        # No database transaction is held during context I/O or geometry work.
        # Recheck before exposing a proposal assembled from a now-stale snapshot.
        with store.transaction() as connection:
            current = store.read(connection, owner, project_id)
        _current(current, body)
        return ConstructionGenerateResult(
            project_id=project_id,
            inventory_revision_id=project.revision_id,
            context_fingerprint=resolved.fingerprint,
            construction=construction,
            fabrication_plan=plan,
            fabrication_report=report,
            fabrication_blockers=tuple(blockers),
        )

    return router
