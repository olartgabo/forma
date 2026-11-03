"""Owner-scoped fabrication reports over saved plans, history and inventory.

Reading a report writes nothing: no event, receipt, preview or revision.
"""

from forma_compiler import CutProcess
from forma_fabrication import fabrication_report
from forma_renderer import StandParameters
from forma_renderer.template import profile_evidence_valid
from forma_replanner import SimulationResult

from forma_api.adapt import carried_operation_ids, plan_ancestors, read_preview
from forma_api.plans import PlanVersion, read_revision
from forma_api.progress import ProgressSnapshot, expected_stock, snapshot
from forma_api.projects import Project, ProjectError
from forma_domain.fabrication_contracts import (
    FabricationInput,
    FabricationReport,
    VersionHistory,
)
from forma_domain.models import Blocker, BuildPlan

# Production reports require measured process and reviewed profile evidence.
# Tests opt in explicitly to schedule synthetic fixtures.
ALLOW_SYNTHETIC = False


def _saved(connection, project_id: str, version_id: str):
    row = connection.execute(
        "SELECT body, process, parameters FROM plans WHERE project_id=? AND version_id=?",
        (project_id, version_id),
    ).fetchone()
    if row is None:
        raise ProjectError(404, "not_found", "Plan not found")
    return (
        PlanVersion.model_validate_json(row[0]),
        CutProcess.model_validate_json(row[1]),
        StandParameters.model_validate_json(row[2]),
    )


def _history(connection, plan: BuildPlan) -> tuple[VersionHistory, ProgressSnapshot]:
    progress = snapshot(connection, plan)
    revision = read_revision(connection, plan.project_id, plan.version_id)
    return (
        VersionHistory(
            plan=plan,
            events=progress.events,
            evidence=progress.evidence,
            carried_operation_ids=revision.carried_completed_operation_ids
            if revision
            else (),
            base_last_event_id=revision.base_last_event_id if revision else None,
        ),
        progress,
    )


def _lineage(connection, plan: BuildPlan):
    ancestors = plan_ancestors(connection, plan.project_id, plan)
    earlier = tuple(_history(connection, p)[0] for p in reversed(ancestors))
    current, progress = _history(connection, plan)
    return earlier + (current,), progress


def _report(project: Project, lineage, remaining, process, parameters, plan):
    context = ()
    if not profile_evidence_valid(
        plan.joint_profiles,
        parameters.profile_evidence,
        plan.project_id,
        allow_synthetic=ALLOW_SYNTHETIC,
    ):
        context = (
            Blocker(
                code="unsupported_profile",
                message="Resolve measured profile evidence before scheduling fabrication.",
            ),
        )
    return fabrication_report(
        FabricationInput(
            project_id=project.id,
            inventory_revision_id=project.revision_id,
            lineage=lineage,
            remaining_stock=remaining,
            declared_tools=project.requirements.tools if project.requirements else None,
            context_blockers=context,
        ),
        process=process,
        allow_synthetic=ALLOW_SYNTHETIC,
    )


def active_report(connection, project: Project, version_id: str) -> FabricationReport:
    if project.active_version_id != version_id:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    version, process, parameters = _saved(connection, project.id, version_id)
    lineage, progress = _lineage(connection, version.plan)
    return _report(
        project,
        lineage,
        progress.expected_remaining_stock,
        process,
        parameters,
        version.plan,
    )


def _proposed(project, lineage, progress, process, parameters, simulation):
    carried = carried_operation_ids(simulation)
    proposed = VersionHistory(
        plan=simulation.plan,
        carried_operation_ids=carried,
        base_last_event_id=progress.last_event_id,
    )
    # The same ledger the version will start from once approved.
    remaining = expected_stock(simulation.plan, set(carried))
    return _report(
        project, lineage + (proposed,), remaining, process, parameters, simulation.plan
    )


class ProposedReports:
    """Reports for several simulations of one active version, loading its
    lineage once."""

    def __init__(self, connection, project: Project):
        self.project = project
        base, self.process, self.parameters = _saved(
            connection, project.id, project.active_version_id
        )
        self.lineage, self.progress = _lineage(connection, base.plan)

    def __call__(self, simulation: SimulationResult) -> FabricationReport:
        return _proposed(
            self.project,
            self.lineage,
            self.progress,
            self.process,
            self.parameters,
            simulation,
        )


def preview_report(connection, project: Project, preview_id: str) -> FabricationReport:
    """Schedule a saved repair preview as if approved, without approving it."""
    if project.active_version_id is None:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    stored = read_preview(connection, project.id, project.active_version_id, preview_id)
    reports = ProposedReports(connection, project)
    if stored.base_last_event_id != reports.progress.last_event_id:
        raise ProjectError(
            409, "stale_version", "Physical history changed; simulate again"
        )
    if stored.preview.version is None:
        raise ProjectError(
            409, "blocked", "This repair candidate has no plan to schedule"
        )
    return reports(stored.preview.simulation)
