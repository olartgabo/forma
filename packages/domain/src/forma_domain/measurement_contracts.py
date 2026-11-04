"""Measurement decisions (#149): which confirmed measurement can change a decision.

A decision names at most one question. It never confirms a value, approves a
design or records physical work; answers go through the existing inventory
confirmation or the #146 assembled-stand measurement flow.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ID, Record, Text
from .piece_references import PieceReference

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
# Every supported fact of a full inventory (32 stocks, 4 facts each) plus the
# build requirements; comparisons never truncate them.
MAX_FACTS = 160
TargetKey = Annotated[str, Field(pattern=r"^[a-z_]+:[A-Za-z0-9_-]{1,96}:[a-z_]+$")]

DecisionOutcome = Literal[
    "question",
    "none_needed",
    "no_feasible_candidate",
    "unsupported",
    "physical_test_required",
    "budget_exhausted",
]
TargetProperty = Literal[
    "width_mm",
    "height_mm",
    "thickness_mm",
    "remaining_length_mm",
    "usable_region",
    "device_mass_g",
    "support_angle_deg",
    "max_footprint_width_mm",
    "max_footprint_height_mm",
    "assembled_stand",
]


class MeasurementTarget(Record):
    """Exactly what to measure. ``key`` is stable across inventory revisions."""

    key: TargetKey
    kind: Literal["stock", "requirement", "assembled_stand"]
    property: TargetProperty
    stock_id: ID | None = None
    label: Text
    pieces: tuple[PieceReference, ...] = Field(default=(), max_length=8)


class CurrentValue(Record):
    """What is saved now. An unconfirmed value is an estimate, never a fact."""

    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["mm", "g", "deg", "none"]
    source: Text
    confirmed: bool


class DecisionThreshold(Record):
    """The governing predicate, computed by the compiler or a cited rule."""

    comparison: Literal["at_least", "within"]
    lower: float = Field(allow_inf_nan=False)
    upper: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["mm", "g", "deg", "m"]
    basis: Text


class MeasurementQuestion(Record):
    question_id: Sha256
    target: MeasurementTarget
    unit: Literal["mm", "g", "deg", "batch"]
    method: Text
    where: Text
    current: CurrentValue | None = None
    threshold: DecisionThreshold | None = None
    required_precision: float | None = Field(default=None, gt=0)
    precision_basis: Text
    affected_candidate_ids: tuple[ID, ...] = Field(default=(), max_length=8)
    affected_case_ids: tuple[ID, ...] = Field(default=(), max_length=8)
    why: Text
    capture: Literal["inventory", "requirements", "stability_measurements"]


class DecisionIdentity(Record):
    project_id: ID
    inventory_revision_id: ID
    active_version_id: ID | None
    last_event_id: ID | None
    context_fingerprint: Sha256
    measurement_record_ids: tuple[ID, ...] = Field(max_length=64)
    declined_target_keys: tuple[TargetKey, ...] = Field(max_length=MAX_FACTS)
    rule_version: Literal["measurement-decision-v1"] = "measurement-decision-v1"


class SavedFact(Record):
    """A saved input the decision depends on, for showing what changed."""

    key: TargetKey
    value: float | None = Field(default=None, allow_inf_nan=False)
    confirmed: bool


class DesignSummary(Record):
    search_id: Sha256
    status: Text
    candidate_ids: tuple[ID, ...] = Field(max_length=2)
    nodes_evaluated: int = Field(ge=0)
    nodes_total: int = Field(ge=0)


class StabilitySummary(Record):
    plan_version_id: ID
    analysis_status: Text
    case_margins_m: tuple[tuple[ID, float | None], ...] = Field(max_length=8)
    required_margin_m: float | None = None


class MeasurementDecision(Record):
    decision_id: Sha256
    identity: DecisionIdentity
    outcome: DecisionOutcome
    question: MeasurementQuestion | None = None
    pending_questions: int = Field(ge=0)
    reasons: tuple[Text, ...] = Field(max_length=16)
    missing_capabilities: tuple[Text, ...] = Field(default=(), max_length=8)
    facts: tuple[SavedFact, ...] = Field(default=(), max_length=MAX_FACTS)
    design: DesignSummary | None = None
    stability: StabilitySummary | None = None
    invalidated: tuple[Text, ...] = Field(default=(), max_length=16)
    # Which server design settings apply and what needs the operator's
    # attention, for example stock the carried settings do not cover.
    settings: tuple[Text, ...] = Field(default=(), max_length=48)
    selection_rule: Text
    physical_verification: Literal["not_attempted"] = "not_attempted"

    @model_validator(mode="after")
    def question_only_when_asked(self):
        if (self.outcome == "question") != (self.question is not None):
            raise ValueError("Only a question outcome carries a question")
        return self


class DecisionChange(Record):
    """Before/after comparison of two decisions for the same project."""

    before_decision_id: Sha256
    after_decision_id: Sha256
    changed_facts: tuple[Text, ...] = Field(max_length=2 * MAX_FACTS + 8)
    decision_changed: bool
    explanation: Text
    after: MeasurementDecision
