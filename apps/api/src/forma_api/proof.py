"""Consistent, photo-excluded reports over existing immutable plan and history data."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime, Field

from forma_api.plans import PlanRevision, PlanVersion, read_revision
from forma_api.progress import ProgressSnapshot, snapshot
from forma_api.projects import Project, ProjectStore
from forma_domain.models import ID, BuildPlan, EvidenceInvalidation, Record, Stock


class ProofVersion(Record):
    inventory_revision_id: ID
    candidate_id: ID
    plan: BuildPlan
    progress: ProgressSnapshot
    state: Literal["active", "historical", "preview"]
    revision: PlanRevision | None = None
    invalidations: tuple[EvidenceInvalidation, ...] = ()


class ProofSnapshot(Record):
    project: Project
    generated_at: AwareDatetime
    versions: tuple[ProofVersion, ...]
    photos_omitted: int = Field(ge=0)
    photo_policy: Literal["excluded"] = "excluded"
    coverage: Literal["versioned_plan_reports"] = "versioned_plan_reports"


def without_photo_ids(stocks: tuple[Stock, ...]) -> tuple[Stock, ...]:
    return tuple(stock.model_copy(update={"image_ids": ()}) for stock in stocks)


def without_plan_photo_ids(plan: BuildPlan) -> BuildPlan:
    return plan.model_copy(update={"stocks": without_photo_ids(plan.stocks)})


def proof_router(store: ProjectStore, authenticate) -> APIRouter:
    router = APIRouter()
    Owner = Annotated[str, Depends(authenticate)]

    @router.get("/{project_id}/proof", response_model=ProofSnapshot)
    def get_proof(project_id: ID, owner: Owner, response: Response):
        response.headers["Cache-Control"] = "no-store"
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            rows = connection.execute(
                "SELECT body FROM plans WHERE project_id=? ORDER BY rowid",
                (project_id,),
            ).fetchall()
            saved = tuple(PlanVersion.model_validate_json(row[0]) for row in rows)
            by_id = {version.version_id: version for version in saved}
            historical = set()
            active = by_id.get(project.active_version_id)
            parent = active.plan.parent_version_id if active else None
            while parent in by_id and parent not in historical:
                historical.add(parent)
                parent = by_id[parent].plan.parent_version_id
            versions = []
            for version in saved:
                progress = snapshot(connection, version.plan)
                revision = read_revision(connection, project_id, version.version_id)
                if revision is not None and revision.simulation.plan is not None:
                    revision = revision.model_copy(
                        update={
                            "simulation": revision.simulation.model_copy(
                                update={
                                    "plan": without_plan_photo_ids(
                                        revision.simulation.plan
                                    )
                                }
                            )
                        }
                    )
                invalidations = tuple(
                    EvidenceInvalidation.model_validate_json(row[0])
                    for row in connection.execute(
                        "SELECT i.body FROM evidence_invalidations i "
                        "JOIN progress_evidence e ON e.id=i.evidence_id "
                        "AND e.project_id=i.project_id "
                        "WHERE i.project_id=? AND e.version_id=? ORDER BY i.rowid",
                        (project_id, version.version_id),
                    )
                )
                versions.append(
                    ProofVersion(
                        inventory_revision_id=version.inventory_revision_id,
                        candidate_id=version.candidate_id,
                        plan=without_plan_photo_ids(version.plan),
                        state="active"
                        if version.version_id == project.active_version_id
                        else "historical"
                        if version.version_id in historical
                        else "preview",
                        revision=revision,
                        invalidations=invalidations,
                        progress=progress.model_copy(
                            update={
                                "expected_remaining_stock": without_photo_ids(
                                    progress.expected_remaining_stock
                                ),
                                "evidence": tuple(
                                    item.model_copy(update={"asset_id": None})
                                    for item in progress.evidence
                                ),
                            }
                        ),
                    )
                )
            photos_omitted = connection.execute(
                "SELECT COUNT(*) FROM media WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            return ProofSnapshot(
                project=project.model_copy(
                    update={"stocks": without_photo_ids(project.stocks)}
                ),
                generated_at=datetime.now(UTC),
                versions=tuple(versions),
                photos_omitted=photos_omitted,
            )

    return router
