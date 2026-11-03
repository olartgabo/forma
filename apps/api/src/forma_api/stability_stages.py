"""Hypothetical mechanics at an authenticated, actually reported construction state."""

from forma_stability.stage import evaluate_stage
from pydantic import Field

from forma_api.projects import ProjectError
from forma_api.stability_runtime import StabilityAnalysisRequest, StabilityContext
from forma_domain.stability_contracts import AnalysisPolicy
from forma_domain.stage_mechanics import StageAnalysisResult, StageSnapshot


class StageAnalysisRequest(StabilityAnalysisRequest):
    snapshot: StageSnapshot
    policy: AnalysisPolicy = Field(
        description="Per-component policy template: required_check_types and tolerances apply to every present component; required_case_ids are replaced with derived component IDs, returned in analysis.policies. Evaluation budget is shared across components. No combined assembly pass is returned."
    )


class StageAnalysisResponse(StabilityContext):
    analysis: StageAnalysisResult
    hypothetical: bool = True


def analyze_stage(project, version, progress, cursor, body, invalidations):
    if (
        project.active_version_id != body.plan_version_id
        or project.revision_id != body.expected_inventory_revision_id
        or cursor != body.expected_last_event_id
    ):
        raise ProjectError(
            409, "stale_version", "Plan, inventory or physical history changed; reload"
        )
    stage = body.snapshot
    if (
        stage.project_id != project.id
        or stage.inventory_revision != project.revision_id
        or stage.plan_version_id != version.version_id
        or stage.history_cursor != cursor
        or set(stage.completed_operation_ids) != set(progress.completed_operation_ids)
    ):
        raise ProjectError(
            422,
            "validation_error",
            "Stage must match this project's reported construction state",
        )
    if stage.basis != "hypothetical":
        raise ProjectError(
            422,
            "validation_error",
            "Stage poses and material properties are hypothetical; observed capture is not yet supported",
        )
    if progress.failed_operation_ids or progress.damaged_part_ids or invalidations:
        raise ProjectError(
            422,
            "validation_error",
            "Failed, damaged or invalidated construction needs a supported reconciled physical snapshot",
        )

    # The pure evaluator accepts provenance descriptions, not evidence authority.
    # This endpoint cannot upgrade submitted numbers into authenticated observations.
    def check(value):
        if isinstance(value, dict):
            if "provenance" in value and (
                value.get("provenance") == "measured"
                or value.get("confirmed")
                or value.get("evidence_ids")
            ):
                raise ProjectError(
                    422,
                    "validation_error",
                    "Hypothetical stage inputs cannot claim measured evidence",
                )
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(stage.model_dump(mode="json"))
    try:
        result = evaluate_stage(version.plan, stage, body.policy)
    except ValueError:
        raise ProjectError(
            422,
            "validation_error",
            "Stage inputs are incompatible with this plan or physical model",
        ) from None
    return StageAnalysisResponse(
        project_id=project.id,
        plan_version_id=version.version_id,
        inventory_revision_id=project.revision_id,
        last_event_id=cursor,
        analysis=result,
    )
