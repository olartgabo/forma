"""Immutable compiler outputs and explicit initial activation; no physical effects."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from forma_compiler import CutProcess
from forma_renderer import StandParameters, compile_stand, render_manual
from forma_renderer.svg import instruction
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from forma_api.projects import Key, Project, ProjectError, ProjectStore
from forma_domain.models import (
    ID,
    Blocker,
    BuildPlan,
    CompilerInput,
    DesignCandidate,
    JointProfile,
    Nonnegative,
    Record,
)


class ManualPanel(Record):
    operation_id: ID
    part_ids: tuple[ID, ...]
    checkpoint_ids: tuple[ID, ...]
    dependency_hash: str
    svg: str
    tools: tuple[str, ...]
    instruction: str


class ManualBillItem(Record):
    id: str
    stock_id: ID
    quantity: float | None
    unit: str
    description: str


class ManualDocument(Record):
    project_id: ID
    version_id: ID
    panels: tuple[ManualPanel, ...]
    bill_of_materials: tuple[ManualBillItem, ...]
    physical_verification: Literal["not_attempted"] = "not_attempted"


class PlanSummary(Record):
    project_id: ID
    version_id: ID
    inventory_revision_id: ID
    candidate_id: ID
    created_at: AwareDatetime


class PlanVersion(PlanSummary):
    plan: BuildPlan
    manual: ManualDocument


class PlanList(Record):
    plans: tuple[PlanSummary, ...]


class CompilePreview(Record):
    expected_revision_id: ID
    idempotency_key: Key
    candidate: DesignCandidate


class PlanCompileResult(Record):
    status: Literal["accepted", "blocked", "needs_measurement", "unsupported"]
    version: PlanVersion | None = None
    blockers: tuple[Blocker, ...] = ()
    replayed: bool = False


class PlanActivation(Record):
    expected_revision_id: ID
    idempotency_key: Key
    user_approved: Literal[True]


class ActivationResult(Record):
    project: Project
    replayed: bool = False


class PlanService:
    def __init__(self, store: ProjectStore, *, allow_synthetic: bool = False):
        self.store = store
        self.allow_synthetic = allow_synthetic

    def _snapshot(self, connection, owner, project_id, body, payload):
        project = self.store.read(connection, owner, project_id)
        digest, replay = self.store.replay(
            connection,
            owner,
            project_id + ":plan-preview",
            body.idempotency_key,
            payload,
        )
        if replay is not None:
            return project, digest, PlanCompileResult.model_validate(replay)
        if project.revision_id != body.expected_revision_id:
            raise ProjectError(409, "stale_version", "Inventory changed; reload it")
        if project.active_version_id is not None:
            raise ProjectError(409, "blocked", "Active plans require a revision")
        return project, digest, None

    def compile_preview(
        self,
        owner: str,
        project_id: str,
        body: CompilePreview,
        *,
        process: CutProcess | None,
        parameters: StandParameters | None,
        joint_profiles: tuple[JointProfile, ...],
        kerf_mm: float | None,
        edge_margin_mm: float | None,
    ) -> PlanCompileResult:
        with self.store.transaction() as connection:
            self.store.read(connection, owner, project_id)
        try:
            selected_kerf = (
                TypeAdapter(Nonnegative).validate_python(kerf_mm, strict=True)
                if kerf_mm is not None
                else None
            )
            selected_margin = (
                TypeAdapter(Nonnegative).validate_python(edge_margin_mm, strict=True)
                if edge_margin_mm is not None
                else None
            )
        except ValidationError:
            return PlanCompileResult(
                status="blocked",
                blockers=(
                    Blocker(
                        code="invalid_reference",
                        message="Selected kerf and margin must be finite nonnegative measurements.",
                    ),
                ),
            )
        payload = {
            "request": body.model_dump(mode="json"),
            "process": process.model_dump(mode="json") if process is not None else None,
            "parameters": parameters.model_dump(mode="json")
            if parameters is not None
            else None,
            "joint_profiles": [
                profile.model_dump(mode="json") for profile in joint_profiles
            ],
            "kerf_mm": selected_kerf,
            "edge_margin_mm": selected_margin,
            "allow_synthetic": self.allow_synthetic,
        }
        with self.store.transaction() as connection:
            project, digest, replay = self._snapshot(
                connection, owner, project_id, body, payload
            )
            if replay is not None:
                return replay
        missing = []
        for absent, message in (
            (not project.inventory_confirmed, "Confirm the saved inventory."),
            (project.requirements is None, "Confirm device and space requirements."),
            (process is None, "Supply measured cutting process evidence."),
            (
                parameters is None,
                "Supply confirmed stand parameters and test conditions.",
            ),
            (not joint_profiles, "Supply reviewed joint profiles and evidence."),
            (kerf_mm is None, "Supply the measured selected kerf in millimeters."),
            (edge_margin_mm is None, "Supply the selected edge margin in millimeters."),
        ):
            if absent:
                missing.append(Blocker(code="missing_measurement", message=message))
        if missing:
            return PlanCompileResult(
                status="needs_measurement", blockers=tuple(missing)
            )
        version_id = "version-" + uuid4().hex
        created_at = datetime.now(UTC)
        # The catalogue is resolved by the trusted caller, never by browser profile IDs.
        constraints = project.requirements.constraints.model_copy(
            update={
                "allowed_profile_ids": tuple(profile.id for profile in joint_profiles)
            }
        )
        request = CompilerInput(
            project_id=project.id,
            version_id=version_id,
            created_at=created_at,
            candidate=body.candidate,
            stocks=project.stocks,
            joint_profiles=joint_profiles,
            constraints=constraints,
            kerf_mm=selected_kerf,
            edge_margin_mm=selected_margin,
            process_evidence_ids=tuple(item.id for item in process.evidence),
        )
        compiled = compile_stand(
            request, parameters, process=process, allow_synthetic=self.allow_synthetic
        )
        if compiled.status != "accepted":
            return PlanCompileResult(status=compiled.status, blockers=compiled.blockers)
        manual = render_manual(
            compiled.plan,
            process=process,
            profile_evidence=parameters.profile_evidence,
            allow_synthetic=self.allow_synthetic,
        )
        if manual.status != "accepted":
            return PlanCompileResult(status=manual.status, blockers=manual.blockers)
        operations = {operation.id: operation for operation in compiled.plan.operations}
        document = ManualDocument(
            project_id=project.id,
            version_id=version_id,
            panels=tuple(
                ManualPanel(
                    operation_id=panel.operation_id,
                    part_ids=panel.part_ids,
                    checkpoint_ids=panel.checkpoint_ids,
                    dependency_hash=panel.dependency_hash,
                    svg=panel.svg,
                    tools=panel.tools,
                    instruction=instruction(
                        operations[panel.operation_id], compiled.plan
                    ),
                )
                for panel in manual.panels
            ),
            bill_of_materials=tuple(
                ManualBillItem.model_validate(item, from_attributes=True)
                for item in manual.bill_of_materials
            ),
        )
        version = PlanVersion(
            project_id=project.id,
            version_id=version_id,
            inventory_revision_id=project.revision_id,
            candidate_id=body.candidate.id,
            created_at=created_at,
            plan=compiled.plan,
            manual=document,
        )
        result = PlanCompileResult(status="accepted", version=version)
        with self.store.transaction() as connection:
            _, digest, replay = self._snapshot(
                connection, owner, project_id, body, payload
            )
            if replay is not None:
                return replay
            count = connection.execute(
                "SELECT COUNT(*) FROM plans WHERE project_id=? AND inventory_revision_id=?",
                (project_id, project.revision_id),
            ).fetchone()[0]
            if count >= 2:
                raise ProjectError(
                    409, "blocked", "At most two designs per inventory revision"
                )
            connection.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    project_id,
                    project.revision_id,
                    version.model_dump_json(),
                    process.model_dump_json(),
                    parameters.model_dump_json(),
                ),
            )
            self.store.remember(
                connection,
                owner,
                project_id + ":plan-preview",
                body.idempotency_key,
                digest,
                result.model_dump(mode="json"),
            )
        return result

    def read(self, connection, project_id: str, version_id: str) -> PlanVersion:
        row = connection.execute(
            "SELECT body FROM plans WHERE project_id=? AND version_id=?",
            (project_id, version_id),
        ).fetchone()
        if row is None:
            raise ProjectError(404, "not_found", "Plan not found")
        return PlanVersion.model_validate_json(row[0])


def plan_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    service = PlanService(store)
    Owner = Annotated[str, Depends(authenticate)]

    @router.get("/{project_id}/plans", response_model=PlanList)
    def list_plans(project_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            rows = connection.execute(
                "SELECT body FROM plans WHERE project_id=? ORDER BY rowid",
                (project_id,),
            ).fetchall()
            return PlanList(
                plans=tuple(
                    PlanSummary(
                        **PlanVersion.model_validate_json(row[0]).model_dump(
                            exclude={"plan", "manual"}
                        )
                    )
                    for row in rows
                )
            )

    @router.get("/{project_id}/versions/{version_id}", response_model=PlanVersion)
    def get_version(project_id: ID, version_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            return service.read(connection, project_id, version_id)

    @router.get("/{project_id}/manual/{version_id}", response_model=ManualDocument)
    def get_manual(project_id: ID, version_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            return service.read(connection, project_id, version_id).manual

    @router.post(
        "/{project_id}/plans/{version_id}/activate", response_model=ActivationResult
    )
    def activate(
        project_id: ID,
        version_id: ID,
        body: PlanActivation,
        owner: Owner,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            digest, replay = store.replay(
                connection,
                owner,
                project_id + ":plan-activation",
                body.idempotency_key,
                {"version_id": version_id, **body.model_dump(mode="json")},
            )
            if replay is not None:
                return replay
            version = service.read(connection, project_id, version_id)
            if (
                project.revision_id != body.expected_revision_id
                or version.inventory_revision_id != project.revision_id
                or project.active_version_id is not None
            ):
                raise ProjectError(
                    409, "stale_version", "Plan or inventory changed; reload it"
                )
            updated = Project(
                **{**project.model_dump(), "active_version_id": version_id}
            )
            connection.execute(
                "UPDATE projects SET body=? WHERE id=? AND owner=?",
                (updated.model_dump_json(), project_id, owner),
            )
            result = ActivationResult(project=updated).model_dump(mode="json")
            store.remember(
                connection,
                owner,
                project_id + ":plan-activation",
                body.idempotency_key,
                digest,
                result,
            )
            return result

    return router
