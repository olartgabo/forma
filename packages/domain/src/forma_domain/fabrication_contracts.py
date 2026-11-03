"""Fabrication report contracts: which planned operation can be attempted next.

A report describes operations and resources, never assembled physical poses.
Modeled access comes from declared rules; it is not observed usability, and a
report never completes a step, authorizes cutting or records physical work.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from forma_domain.models import (
    ID,
    Blocker,
    BuildPlan,
    Evidence,
    PhysicalEvent,
    Record,
    Stock,
    Text,
)

FABRICATION_RULES_VERSION = "fabrication-rules-v1"

OperationType = Literal[
    "measure",
    "mark",
    "cut_rect",
    "cut_slot",
    "fold",
    "insert_tab",
    "tape_joint",
    "tie_joint",
    "attach_brace",
    "detach",
    "inspect",
    "functional_test",
]
ToolClass = Literal["cutting_tool", "ruler", "marker", "scale", "protractor"]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class VersionHistory(Record):
    """One plan version and the physical reports recorded against it.

    ``carried_operation_ids`` and ``base_last_event_id`` are the approved
    revision boundary; a root version has neither."""

    plan: BuildPlan
    events: tuple[PhysicalEvent, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    carried_operation_ids: tuple[ID, ...] = ()
    base_last_event_id: ID | None = None


class FabricationInput(Record):
    """Lineage from the root version to the version being scheduled (last)."""

    project_id: ID
    inventory_revision_id: ID
    lineage: tuple[VersionHistory, ...] = Field(min_length=1, max_length=32)
    remaining_stock: tuple[Stock, ...]
    declared_tools: tuple[Text, ...] | None
    context_blockers: tuple[Blocker, ...] = ()

    @model_validator(mode="after")
    def scope(self):
        if any(v.plan.project_id != self.project_id for v in self.lineage):
            raise ValueError("lineage belongs to another project")
        return self


class ToolCheck(Record):
    tool: ToolClass
    status: Literal["declared", "not_declared", "unknown"]
    declared_name: Text | None


class OperationReadiness(Record):
    operation_id: ID
    operation_type: OperationType
    status: Literal["completed", "ready", "waiting", "blocked"]
    completed_in_version_id: ID | None
    waiting_on_operation_ids: tuple[ID, ...]
    blockers: tuple[Blocker, ...]
    tools: tuple[ToolCheck, ...]
    required_confirmations: tuple[Text, ...]
    next_state_id: ID | None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "ready") != (self.next_state_id is not None):
            raise ValueError("only a ready operation has a next execution state")
        if self.status == "blocked" and not self.blockers:
            raise ValueError("a blocked operation requires blockers")
        if self.status in ("ready", "completed") and self.blockers:
            raise ValueError("ready or completed operations carry no blockers")
        if (self.status == "completed") != (self.completed_in_version_id is not None):
            raise ValueError("completion requires its recording version")
        return self


class OrderStep(Record):
    operation_id: ID
    state_id: ID
    reordered: bool


class FabricationSnapshot(Record):
    """Exact inputs a report was computed from."""

    project_id: ID
    version_id: ID
    inventory_revision_id: ID
    last_event_id: ID | None
    plan_sha256: Sha256
    history_sha256: Sha256
    process_sha256: Sha256
    rules_version: Literal["fabrication-rules-v1"]
    compiler_version: Text


class FabricationReport(Record):
    snapshot: FabricationSnapshot
    status: Literal["ready", "blocked", "complete", "history_conflict"]
    current_state_id: ID
    attached_joint_ids: tuple[ID, ...]
    damaged_part_ids: tuple[ID, ...]
    failed_operation_ids: tuple[ID, ...]
    next_operation_id: ID | None
    operations: tuple[OperationReadiness, ...]
    supported_order: tuple[OrderStep, ...]
    order_status: Literal["complete", "blocked", "cycle"]
    order_blockers: tuple[Blocker, ...]
    blockers: tuple[Blocker, ...]
    access_basis: Literal["declared_rules"]
    observed_usability: Literal["not_assessed"]

    @model_validator(mode="after")
    def consistent(self):
        ready = {o.operation_id for o in self.operations if o.status == "ready"}
        if (self.status == "ready") != bool(ready):
            raise ValueError("report status disagrees with ready operations")
        if self.next_operation_id is not None and self.next_operation_id not in ready:
            raise ValueError("next operation must be ready")
        if self.status == "history_conflict" and not self.blockers:
            raise ValueError("history conflicts require blockers")
        if (self.order_status == "complete") == bool(self.order_blockers):
            raise ValueError("an incomplete order requires blockers")
        return self
