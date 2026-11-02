"""Consistent, photo-excluded reports over existing immutable plan and history data."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime, Field

from forma_api.plans import PlanVersion
from forma_api.progress import ProgressSnapshot, snapshot
from forma_api.projects import Project, ProjectStore
from forma_domain.models import ID, BuildPlan, Record, Stock


class ProofVersion(Record):
    inventory_revision_id: ID
    candidate_id: ID
    plan: BuildPlan
    progress: ProgressSnapshot


class ProofSnapshot(Record):
    project: Project
    generated_at: AwareDatetime
    versions: tuple[ProofVersion, ...]
    photos_omitted: int = Field(ge=0)
    photo_policy: Literal["excluded"] = "excluded"
    coverage: Literal["initial_plan_reports"] = "initial_plan_reports"


def without_photo_ids(stocks: tuple[Stock, ...]) -> tuple[Stock, ...]:
    return tuple(stock.model_copy(update={"image_ids": ()}) for stock in stocks)


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
            versions = []
            for row in rows:
                version = PlanVersion.model_validate_json(row[0])
                progress = snapshot(connection, version.plan)
                versions.append(
                    ProofVersion(
                        inventory_revision_id=version.inventory_revision_id,
                        candidate_id=version.candidate_id,
                        plan=version.plan.model_copy(
                            update={"stocks": without_photo_ids(version.plan.stocks)}
                        ),
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
