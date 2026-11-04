"""Owner-scoped fabrication reports over saved plans, history and inventory.

Reading a report writes nothing: no event, receipt, preview or revision.
"""

from typing import Annotated, Literal

from forma_compiler import CutProcess
from forma_fabrication import fabrication_report
from forma_renderer import StandParameters
from forma_renderer.template import profile_evidence_valid
from forma_replanner import SimulationResult
from pydantic import Field, StringConstraints, model_validator

from forma_api.adapt import (
    ConnectorMeasurement,
    RepairBase,
    carried_operation_ids,
    confirmed_remaining,
    plan_ancestors,
    read_preview,
)
from forma_api.plans import PlanVersion, read_revision
from forma_api.progress import ProgressSnapshot, snapshot
from forma_api.projects import Project, ProjectError
from forma_api.recognized_items_runtime import hold_blockers, require_no_holds
from forma_domain.fabrication_contracts import (
    FabricationInput,
    FabricationReport,
    VersionHistory,
)
from forma_domain.models import ID, Blocker, BuildPlan, Record

# Production reports require measured process and reviewed profile evidence.
# Tests opt in explicitly to schedule synthetic fixtures.
ALLOW_SYNTHETIC = False


class FabricationAssessment(Record):
    """User-confirmed inputs for one read-only active-version assessment."""

    expected_inventory_revision_id: ID
    expected_last_event_id: ID | None
    connector_measurements: tuple[ConnectorMeasurement, ...] = Field(
        default=(), max_length=32
    )
    remaining_confirmed: Literal[True] | None = None
    additional_tools: tuple[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
        ],
        ...,
    ] = Field(default=(), max_length=32)
    tools_confirmed: Literal[True] | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict):
            for items, flag in (
                ("connector_measurements", "remaining_confirmed"),
                ("additional_tools", "tools_confirmed"),
            ):
                if value.get(items) and value.get(flag) is not True:
                    raise ValueError("Explicit user confirmation is required")
        return value

    @model_validator(mode="after")
    def distinct(self):
        for items, flag in (
            (self.connector_measurements, self.remaining_confirmed),
            (self.additional_tools, self.tools_confirmed),
        ):
            if bool(items) != (flag is True):
                raise ValueError("Confirmation applies only to supplied inputs")
        if len({item.stock_id for item in self.connector_measurements}) != len(
            self.connector_measurements
        ):
            raise ValueError("Duplicate connector measurements")
        if len({tool.casefold() for tool in self.additional_tools}) != len(
            self.additional_tools
        ):
            raise ValueError("Duplicate tool names")
        return self


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
    if len(ancestors) >= 32:
        raise ProjectError(
            409,
            "blocked",
            "Fabrication reports support at most 32 plan versions. Review this history before continuing.",
        )
    earlier = tuple(_history(connection, p)[0] for p in reversed(ancestors))
    current, progress = _history(connection, plan)
    return earlier + (current,), progress


def _report(
    project: Project,
    lineage,
    remaining,
    process,
    parameters,
    plan,
    additional_tools=(),
    held=(),
):
    """``held`` are material-hold blockers: the report still describes the
    recorded history, but no order is offered while a material is held."""
    if len(lineage) > 32:
        raise ProjectError(
            409,
            "blocked",
            "Fabrication reports support at most 32 plan versions, including a proposed revision.",
        )
    context = tuple(held)
    if not profile_evidence_valid(
        plan.joint_profiles,
        parameters.profile_evidence,
        plan.project_id,
        allow_synthetic=ALLOW_SYNTHETIC,
    ):
        context += (
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
            declared_tools=tuple(
                dict.fromkeys(
                    (project.requirements.tools if project.requirements else ())
                    + additional_tools
                )
            )
            if additional_tools
            else project.requirements.tools
            if project.requirements
            else None,
            context_blockers=context,
            profile_evidence=parameters.profile_evidence,
        ),
        process=process,
        allow_synthetic=ALLOW_SYNTHETIC,
    )


def active_report(connection, project: Project, version_id: str) -> FabricationReport:
    if project.active_version_id != version_id:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    version, process, parameters = _saved(connection, project.id, version_id)
    lineage, progress = _lineage(connection, version.plan)
    # Readable as history while a material is held, but marked blocked.
    return _report(
        project,
        lineage,
        progress.expected_remaining_stock,
        process,
        parameters,
        version.plan,
        held=hold_blockers(connection, project.id),
    )


def _proposed(project, lineage, progress, process, parameters, simulation, remaining):
    carried = carried_operation_ids(simulation)
    proposed = VersionHistory(
        plan=simulation.plan,
        carried_operation_ids=carried,
        base_last_event_id=progress.last_event_id,
    )
    # The authoritative measured current ledger; future work is not consumed.
    return _report(
        project, lineage + (proposed,), remaining, process, parameters, simulation.plan
    )


class ProposedReports:
    """Reports for several simulations of one active version, loading its
    lineage once."""

    def __init__(self, connection, project: Project, remaining):
        self.project = project
        self.remaining = remaining
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
            self.remaining,
        )


def assess_active(
    connection, project: Project, version_id: str, body: FabricationAssessment
) -> FabricationReport:
    if (
        project.active_version_id != version_id
        or project.revision_id != body.expected_inventory_revision_id
    ):
        raise ProjectError(409, "stale_version", "The project changed; reload it")
    base = RepairBase(connection, project.id, version_id)
    if base.progress.last_event_id != body.expected_last_event_id:
        raise ProjectError(409, "stale_version", "Physical history changed; reload it")
    remaining = (
        confirmed_remaining(base, body.connector_measurements, require_all=False)
        if body.connector_measurements
        else base.progress.expected_remaining_stock
    )
    original = {stock.id: stock for stock in base.progress.expected_remaining_stock}
    if any(
        stock.remaining_length_mm.value != original[stock.id].remaining_length_mm.value
        for stock in remaining
    ):
        raise ProjectError(
            422,
            "validation_error",
            "Record material loss or reconcile a different measured balance before continuing",
        )
    require_no_holds(connection, project.id, "Fabrication assessment")
    lineage, _ = _lineage(connection, base.version.plan)
    return _report(
        project,
        lineage,
        remaining,
        base.process,
        base.parameters,
        base.version.plan,
        body.additional_tools,
    )


def preview_report(connection, project: Project, preview_id: str) -> FabricationReport:
    """Schedule a saved repair preview as if approved, without approving it."""
    if project.active_version_id is None:
        raise ProjectError(409, "stale_version", "The active plan changed; reload it")
    # A preview saved before a material was held stays saved, but is not
    # scheduled while the hold remains.
    require_no_holds(connection, project.id, "Scheduling this repair")
    stored = read_preview(connection, project.id, project.active_version_id, preview_id)
    reports = ProposedReports(connection, project, stored.remaining_stock)
    if stored.base_last_event_id != reports.progress.last_event_id:
        raise ProjectError(
            409, "stale_version", "Physical history changed; simulate again"
        )
    if stored.preview.version is None:
        raise ProjectError(
            409, "blocked", "This repair candidate has no plan to schedule"
        )
    trusted = RepairBase(connection, project.id, project.active_version_id)
    simulation = trusted.simulate(stored.preview.patch, stored.remaining_stock)
    if simulation != stored.preview.simulation:
        raise ProjectError(
            409, "stale_version", "Repair inputs changed; simulate again"
        )
    return reports(simulation)
