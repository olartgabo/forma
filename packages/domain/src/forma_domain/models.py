"""Offline immutable contracts. Geometry feasibility belongs to the compiler."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Condition = Literal["usable", "damaged", "uncertain"]
Reversibility = Literal["reversible", "lossy", "irreversible", "not_applicable"]


class Record(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_default=True, allow_inf_nan=False
    )


class Measurement(Record):
    value: float | None = Field(allow_inf_nan=False)
    unit: Literal["mm", "g", "deg"]
    source: Literal["user_ruler", "known_reference", "calculated", "unknown"]
    confirmed: bool
    evidence_ids: tuple[ID, ...] = ()

    @model_validator(mode="after")
    def known(self):
        if self.value is None and (self.confirmed or self.source != "unknown"):
            raise ValueError(
                "unknown measurement must be unconfirmed with unknown source"
            )
        if self.value is not None and self.source == "unknown":
            raise ValueError("known value requires provenance")
        return self


class Rect(Record):
    x: Nonnegative
    y: Nonnegative
    width: Positive
    height: Positive
    rotation_deg: Literal[0, 90] = 0


class Region(Record):
    id: ID
    geometry: Rect


class Stock(Record):
    id: ID
    kind: Literal["sheet", "strip", "tape", "cord"]
    material: Literal["cardboard", "paperboard", "other_supported"]
    width_mm: Measurement
    height_mm: Measurement
    thickness_mm: Measurement
    remaining_length_mm: Measurement
    condition: Condition
    usable_regions: tuple[Region, ...] = ()
    image_ids: tuple[ID, ...] = ()
    allowed_rotations_deg: tuple[Literal[0, 90], ...] = Field(
        default=(0, 90), min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def dimensions(self):
        for name in ("width_mm", "height_mm", "thickness_mm", "remaining_length_mm"):
            measurement = getattr(self, name)
            if measurement.unit != "mm" or (
                measurement.value is not None
                and (
                    measurement.value < 0
                    if name == "remaining_length_mm"
                    else measurement.value <= 0
                )
            ):
                raise ValueError(f"{name} requires positive mm or unknown")
        unique(self.usable_regions, "regions")
        return self


class Feature(Record):
    id: ID
    kind: Literal["tab", "slot", "fold", "mark"]
    geometry: Rect


class Part(Record):
    id: ID
    source_stock_id: ID
    source_region_id: ID
    geometry: Rect
    features: tuple[Feature, ...] = ()
    condition: Condition


class JointProfile(Record):
    id: ID
    strategy: Literal["tab_slot", "fold_brace", "tape", "tie"]
    status: Literal["experimental", "tested"]
    material: Literal["cardboard", "paperboard", "other_supported"]
    thickness_min_mm: Positive | None = None
    thickness_max_mm: Positive | None = None
    tolerated_error_mm: Nonnegative | None = None
    test_evidence_ids: tuple[ID, ...] = ()
    limitations: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def tested(self):
        if self.thickness_min_mm is not None and self.thickness_max_mm is not None:
            if self.thickness_min_mm > self.thickness_max_mm:
                raise ValueError("inverted thickness limits")
        if self.status == "tested" and (
            not self.test_evidence_ids
            or self.tolerated_error_mm is None
            or self.thickness_min_mm is None
            or self.thickness_max_mm is None
        ):
            raise ValueError("tested profile requires measured limits and evidence")
        return self


class Joint(Record):
    id: ID
    profile_id: ID
    part_ids: tuple[ID, ...] = Field(min_length=2)
    interface_feature_ids: tuple[ID, ...] = ()
    confirmed_accessible: bool | None = None


class Preconditions(Record):
    confirmed_measurement_ids: tuple[ID, ...] = ()
    accessible_part_ids: tuple[ID, ...] = ()
    required_joint_ids: tuple[ID, ...] = ()
    safe_tools_confirmed: bool = False
    human_checks: tuple[Text, ...] = ()


class Effects(Record):
    created_part_ids: tuple[ID, ...] = ()
    changed_part_ids: tuple[ID, ...] = ()
    attached_joint_ids: tuple[ID, ...] = ()
    detached_joint_ids: tuple[ID, ...] = ()
    consumed_region_ids: tuple[ID, ...] = ()
    created_offcuts: tuple[Region, ...] = ()
    invalidated_checkpoint_ids: tuple[ID, ...] = ()


class OperationBase(Record):
    id: ID
    part_ids: tuple[ID, ...] = ()
    stock_ids: tuple[ID, ...] = ()
    depends_on: tuple[ID, ...] = ()
    expected_state_id: ID
    requires_user_confirmation: bool = True
    preconditions: Preconditions
    effects: Effects

    @model_validator(mode="after")
    def irreversible_confirmation(self):
        if (
            getattr(self, "reversible", None) == "irreversible"
            and not self.requires_user_confirmation
        ):
            raise ValueError(
                "irreversible operations require explicit user confirmation"
            )
        return self


class MeasureArgs(Record):
    target_id: ID
    measurement_id: ID
    dimension: Literal["width", "height", "thickness", "length", "mass", "angle"]
    method: Literal["ruler", "scale", "protractor", "known_reference"]


class MarkArgs(Record):
    part_id: ID
    feature_id: ID
    geometry: Rect


class CutRectArgs(Record):
    stock_id: ID
    source_region_id: ID
    child_part_ids: tuple[ID, ...] = Field(min_length=1)
    kerf_mm: Nonnegative
    edge_margin_mm: Nonnegative


class CutSlotArgs(MarkArgs):
    profile_id: ID
    kerf_mm: Nonnegative
    edge_margin_mm: Nonnegative


class FoldArgs(Record):
    part_id: ID
    feature_id: ID
    start_x_mm: Nonnegative
    start_y_mm: Nonnegative
    end_x_mm: Nonnegative
    end_y_mm: Nonnegative
    angle_deg: Annotated[float, Field(gt=-180, lt=180, allow_inf_nan=False)]
    direction: Literal["mountain", "valley"]
    reachable_face: Literal["front", "back"]


class JoinArgs(Record):
    joint_id: ID


class InsertTabArgs(JoinArgs):
    tab_feature_id: ID
    slot_feature_id: ID


class ConsumableJointArgs(JoinArgs):
    stock_id: ID
    length_mm: Positive


class AttachBraceArgs(JoinArgs):
    brace_part_id: ID
    underlying_joint_ids: tuple[ID, ...] = Field(min_length=1)


class DetachArgs(JoinArgs):
    supported_inverse: Literal[
        "remove_tab", "peel_tape", "untie", "cut_cord", "remove_brace"
    ]
    material_loss_stock_ids: tuple[ID, ...] = ()


class InspectArgs(Record):
    target_ids: tuple[ID, ...] = Field(min_length=1)
    checkpoint_id: ID
    method: Literal["photo", "ruler", "human_inspection"]


class FunctionalTestArgs(Record):
    checkpoint_id: ID
    procedure: Text
    device_label: Text
    mass_g: Positive | None
    duration_seconds: Positive
    surface: Text
    pass_criteria: tuple[Text, ...] = Field(min_length=1)


class Measure(OperationBase):
    type: Literal["measure"]
    args: MeasureArgs
    reversible: Literal["not_applicable"] = "not_applicable"


class Mark(OperationBase):
    type: Literal["mark"]
    args: MarkArgs
    reversible: Literal["lossy"] = "lossy"


class CutRect(OperationBase):
    type: Literal["cut_rect"]
    args: CutRectArgs
    reversible: Literal["irreversible"] = "irreversible"
    requires_user_confirmation: Literal[True] = True


class CutSlot(OperationBase):
    type: Literal["cut_slot"]
    args: CutSlotArgs
    reversible: Literal["irreversible"] = "irreversible"
    requires_user_confirmation: Literal[True] = True


class Fold(OperationBase):
    type: Literal["fold"]
    args: FoldArgs
    reversible: Literal["lossy"] = "lossy"


class InsertTab(OperationBase):
    type: Literal["insert_tab"]
    args: InsertTabArgs
    reversible: Literal["reversible", "lossy"]


class TapeJoint(OperationBase):
    type: Literal["tape_joint"]
    args: ConsumableJointArgs
    reversible: Literal["lossy", "irreversible"]


class TieJoint(OperationBase):
    type: Literal["tie_joint"]
    args: ConsumableJointArgs
    reversible: Literal["reversible", "lossy"]


class AttachBrace(OperationBase):
    type: Literal["attach_brace"]
    args: AttachBraceArgs
    reversible: Reversibility


class Detach(OperationBase):
    type: Literal["detach"]
    args: DetachArgs
    reversible: Literal["reversible", "lossy"]


class Inspect(OperationBase):
    type: Literal["inspect"]
    args: InspectArgs
    reversible: Literal["not_applicable"] = "not_applicable"


class FunctionalTest(OperationBase):
    type: Literal["functional_test"]
    args: FunctionalTestArgs
    reversible: Literal["not_applicable"] = "not_applicable"


Operation = Annotated[
    Measure
    | Mark
    | CutRect
    | CutSlot
    | Fold
    | InsertTab
    | TapeJoint
    | TieJoint
    | AttachBrace
    | Detach
    | Inspect
    | FunctionalTest,
    Field(discriminator="type"),
]


class Checkpoint(Record):
    id: ID
    after_operation_id: ID
    method: Literal["photo", "ruler", "human_inspection", "functional_test"]
    description: Text
    invalidated_by: tuple[ID, ...] = ()


class Constraints(Record):
    device_mass_g: Measurement
    support_angle_deg: Measurement
    max_footprint_width_mm: Measurement
    max_footprint_height_mm: Measurement
    allowed_profile_ids: tuple[ID, ...] = ()
    allow_purchases: bool = False

    @model_validator(mode="after")
    def units(self):
        for name, unit in (
            ("device_mass_g", "g"),
            ("support_angle_deg", "deg"),
            ("max_footprint_width_mm", "mm"),
            ("max_footprint_height_mm", "mm"),
        ):
            if getattr(self, name).unit != unit:
                raise ValueError(f"{name} requires {unit}")
        return self


def unique(records, label):
    ids = [r.id for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} IDs")


class BuildPlan(Record):
    project_id: ID
    version_id: ID
    parent_version_id: ID | None = None
    family: Literal["tabletop_fixture_v1"] = "tabletop_fixture_v1"
    status: Literal["draft", "validated", "blocked", "active"]
    stocks: tuple[Stock, ...]
    parts: tuple[Part, ...]
    joint_profiles: tuple[JointProfile, ...]
    joints: tuple[Joint, ...]
    operations: tuple[Operation, ...]
    checkpoints: tuple[Checkpoint, ...]
    constraints: Constraints
    compiler_version: Text
    created_at: AwareDatetime

    @model_validator(mode="after")
    def references(self):
        groups = (
            self.stocks,
            self.parts,
            self.joint_profiles,
            self.joints,
            self.operations,
            self.checkpoints,
            tuple(r for s in self.stocks for r in s.usable_regions),
            tuple(f for p in self.parts for f in p.features),
            tuple(r for o in self.operations for r in o.effects.created_offcuts),
        )
        unique(tuple(r for group in groups for r in group), "plan")
        stocks = {s.id for s in self.stocks}
        parts = {p.id for p in self.parts}
        profiles = {p.id for p in self.joint_profiles}
        joints = {j.id for j in self.joints}
        operations = {o.id for o in self.operations}
        checkpoints = {c.id for c in self.checkpoints}
        features = {f.id for p in self.parts for f in p.features}
        regions = {r.id for s in self.stocks for r in s.usable_regions} | {
            r.id for o in self.operations for r in o.effects.created_offcuts
        }

        def refs(values, allowed, label):
            if len(values) != len(set(values)) or not set(values) <= allowed:
                raise ValueError(f"invalid or duplicate {label} reference")

        for p in self.parts:
            refs((p.source_stock_id,), stocks, "stock")
            refs((p.source_region_id,), regions, "region")
        for j in self.joints:
            refs((j.profile_id,), profiles, "profile")
            refs(j.part_ids, parts, "part")
            refs(j.interface_feature_ids, features, "feature")
        seen = set()
        for o in self.operations:
            refs(o.part_ids, parts, "part")
            refs(o.stock_ids, stocks, "stock")
            refs(o.depends_on, seen, "preceding operation")
            seen.add(o.id)
            refs(o.preconditions.accessible_part_ids, parts, "accessible part")
            refs(o.preconditions.required_joint_ids, joints, "required joint")
            e = o.effects
            for values in (e.created_part_ids, e.changed_part_ids):
                refs(values, parts, "effect part")
            for values in (e.attached_joint_ids, e.detached_joint_ids):
                refs(values, joints, "effect joint")
            refs(e.consumed_region_ids, regions, "consumed region")
            refs(e.invalidated_checkpoint_ids, checkpoints, "checkpoint")
            a = o.args
            for field, allowed in (
                ("part_id", parts),
                ("stock_id", stocks),
                ("profile_id", profiles),
                ("joint_id", joints),
                ("source_region_id", regions),
                ("feature_id", features),
                ("tab_feature_id", features),
                ("slot_feature_id", features),
                ("brace_part_id", parts),
                ("checkpoint_id", checkpoints),
            ):
                if hasattr(a, field):
                    refs((getattr(a, field),), allowed, field)
            for field, allowed in (
                ("child_part_ids", parts),
                ("underlying_joint_ids", joints),
                ("material_loss_stock_ids", stocks),
                ("target_ids", parts | stocks | joints),
            ):
                if hasattr(a, field):
                    refs(getattr(a, field), allowed, field)
            if isinstance(a, MeasureArgs):
                refs((a.target_id,), stocks | parts | joints, "measurement target")
        measurement_ids = {
            o.args.measurement_id for o in self.operations if isinstance(o, Measure)
        }
        if len(measurement_ids) != sum(isinstance(o, Measure) for o in self.operations):
            raise ValueError("duplicate measurement IDs")
        if measurement_ids & {r.id for group in groups for r in group}:
            raise ValueError("measurement IDs collide with plan IDs")
        for o in self.operations:
            refs(
                o.preconditions.confirmed_measurement_ids,
                measurement_ids,
                "measurement",
            )
        for c in self.checkpoints:
            refs((c.after_operation_id,), operations, "checkpoint operation")
            refs(c.invalidated_by, operations, "invalidation operation")
        refs(self.constraints.allowed_profile_ids, profiles, "allowed profile")
        return self


VerificationState = Literal[
    "not_checked",
    "user_confirmed",
    "vision_observed",
    "failed",
    "unknown",
    "invalidated",
]


class PhysicalEvent(Record):
    id: ID
    project_id: ID
    version_id: ID
    operation_id: ID | None = None
    kind: Literal["operation_confirmed", "observation", "measurement", "damage", "test"]
    evidence_ids: tuple[ID, ...] = ()
    recorded_at: AwareDatetime
    actor: Literal["user", "system"]
    observation: Text
    verification_state: VerificationState
    test_result: Literal["passed", "failed", "not_attempted"] | None = None

    @model_validator(mode="after")
    def physical_claim(self):
        if self.kind in ("operation_confirmed", "test") and self.actor != "user":
            raise ValueError("physical completion and tests require user report")
        if self.kind == "operation_confirmed" and self.operation_id is None:
            raise ValueError("completion requires operation")
        if (self.kind == "test") != (self.test_result is not None):
            raise ValueError("test results belong only to test events")
        if self.test_result is not None:
            expected = {
                "passed": "user_confirmed",
                "failed": "failed",
                "not_attempted": "not_checked",
            }[self.test_result]
            if self.verification_state != expected:
                raise ValueError("test result and verification state disagree")
        return self


class Evidence(Record):
    id: ID
    project_id: ID
    version_id: ID
    kind: Literal[
        "photo", "measurement", "user_report", "model_interpretation", "physical_test"
    ]
    provenance: Literal["user", "model", "compiler", "synthetic_fixture"]
    asset_id: ID | None = None
    part_ids: tuple[ID, ...] = ()
    operation_ids: tuple[ID, ...] = ()
    checkpoint_ids: tuple[ID, ...] = ()
    recorded_at: AwareDatetime
    description: Text
    verification_state: VerificationState

    @model_validator(mode="after")
    def provenance_claim(self):
        if self.verification_state == "user_confirmed" and self.provenance != "user":
            raise ValueError("user confirmation requires user provenance")
        if self.kind == "physical_test" and self.provenance != "user":
            raise ValueError("physical tests require user provenance")
        return self


class EvidenceInvalidation(Record):
    id: ID
    evidence_id: ID
    invalidated_for_version_id: ID
    reason: Text
    recorded_at: AwareDatetime


class MaterialTransaction(Record):
    id: ID
    project_id: ID
    version_id: ID
    operation_id: ID
    source_stock_id: ID
    kind: Literal["consume", "offcut", "waste", "salvage", "damage"]
    source_region_id: ID | None = None
    output_region: Region | None = None
    quantity: Positive
    unit: Literal["mm", "mm2"]
    recorded_at: AwareDatetime
    physical_event_id: ID


class Blocker(Record):
    code: Literal[
        "invalid_reference",
        "missing_measurement",
        "stock_exhausted",
        "geometry_invalid",
        "unsupported_profile",
        "invalid_order",
        "irreversible_conflict",
        "needs_confirmation",
        "stale_version",
        "unsupported",
        "no_feasible_repair",
    ]
    message: Text
    target_ids: tuple[ID, ...] = ()


class DesignCandidate(Record):
    id: ID
    family: Literal["tabletop_fixture_v1"]
    support_angle_deg: Annotated[float, Field(gt=0, lt=90)]
    part_width_mm: Positive
    part_height_mm: Positive
    panel_count: Annotated[int, Field(ge=2, le=6)]
    stock_ids: tuple[ID, ...] = Field(min_length=1, max_length=8)
    profile_ids: tuple[ID, ...] = Field(min_length=1, max_length=8)
    assumptions: tuple[Text, ...] = Field(max_length=8)


class DesignProposals(Record):
    candidates: tuple[DesignCandidate, ...] = Field(max_length=2)
    questions: tuple[Text, ...] = Field(max_length=8)


class RepairPatch(Record):
    """Flat parameter edits, not executable operations or arbitrary JSON patches."""

    id: ID
    base_version_id: ID
    kind: Literal[
        "resize_part", "replace_joint_profile", "replace_part", "change_angle"
    ]
    target_id: ID
    replacement_stock_id: ID | None
    replacement_profile_id: ID | None
    width_mm: Positive | None
    height_mm: Positive | None
    angle_deg: Annotated[float, Field(gt=0, lt=90)] | None
    rationale: Text

    @model_validator(mode="after")
    def required_parameters(self):
        required = {
            "resize_part": ("width_mm", "height_mm"),
            "replace_joint_profile": ("replacement_profile_id",),
            "replace_part": ("replacement_stock_id",),
            "change_angle": ("angle_deg",),
        }[self.kind]
        fields = (
            "width_mm",
            "height_mm",
            "replacement_profile_id",
            "replacement_stock_id",
            "angle_deg",
        )
        if any(getattr(self, f) is None for f in required) or any(
            getattr(self, f) is not None for f in fields if f not in required
        ):
            raise ValueError("patch parameters must match kind")
        return self


class RepairProposals(Record):
    candidates: tuple[RepairPatch, ...] = Field(max_length=3)
    questions: tuple[Text, ...] = Field(max_length=8)


class DiagnosisProposal(Record):
    visible_observations: tuple[Text, ...] = Field(max_length=12)
    hypotheses: tuple[Text, ...] = Field(max_length=8)
    questions_or_measurements: tuple[Text, ...] = Field(max_length=8)
    affected_ids: tuple[ID, ...] = Field(max_length=20)
    failure_type: Literal[
        "torn_slot",
        "wrong_dimension",
        "missing_material",
        "damaged_part",
        "unstable",
        "unknown",
    ]


class AdaptProposal(Record):
    id: ID
    base_version_id: ID
    proposed_plan: BuildPlan
    preserved_operation_ids: tuple[ID, ...]
    undo_operations: tuple[Operation, ...]
    redo_operation_ids: tuple[ID, ...]
    newly_required_operation_ids: tuple[ID, ...]
    invalidated_checkpoint_ids: tuple[ID, ...]
    material_transactions: tuple[MaterialTransaction, ...]
    required_new_stock_ids: tuple[ID, ...]
    blockers: tuple[Blocker, ...]
    rationale: Text


class Mutation(Record):
    project_id: ID
    expected_version_id: ID
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]


class ConfirmInventory(Mutation):
    stocks: tuple[Stock, ...] = Field(min_length=1, max_length=32)
    user_confirmed: Literal[True]

    @model_validator(mode="after")
    def ids(self):
        unique(self.stocks, "stock")
        return self


class AppendPhysicalEvent(Mutation):
    event: PhysicalEvent

    @model_validator(mode="after")
    def scope(self):
        if (
            self.event.project_id != self.project_id
            or self.event.version_id != self.expected_version_id
        ):
            raise ValueError("event project/version differs from mutation")
        return self


class CommitRevision(Mutation):
    proposal_id: ID
    user_approved: Literal[True]


class MutationResult(Record):
    project_id: ID
    active_version_id: ID
    idempotency_key: str
    replayed: bool


class ErrorEnvelope(Record):
    code: Literal[
        "validation_error",
        "not_found",
        "forbidden",
        "stale_version",
        "idempotency_conflict",
        "blocked",
    ]
    message: Text
    blockers: tuple[Blocker, ...] = ()


class CompilerInput(Record):
    project_id: ID
    version_id: ID
    created_at: AwareDatetime
    candidate: DesignCandidate
    stocks: tuple[Stock, ...]
    joint_profiles: tuple[JointProfile, ...]
    constraints: Constraints
    kerf_mm: Nonnegative
    edge_margin_mm: Nonnegative
    process_evidence_ids: tuple[ID, ...]


class CompilerResult(Record):
    status: Literal["accepted", "blocked", "needs_measurement", "unsupported"]
    plan: BuildPlan | None
    blockers: tuple[Blocker, ...]

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "accepted":
            if self.plan is None or self.blockers:
                raise ValueError("accepted compilation requires plan without blockers")
        elif self.plan is not None or not self.blockers:
            raise ValueError("rejected compilation requires blockers without plan")
        return self


class ReplannerInput(Record):
    base_plan: BuildPlan
    events: tuple[PhysicalEvent, ...]
    evidence: tuple[Evidence, ...]
    material_transactions: tuple[MaterialTransaction, ...]
    remaining_stock: tuple[Stock, ...]
    patch: RepairPatch

    @model_validator(mode="after")
    def base(self):
        if self.patch.base_version_id != self.base_plan.version_id:
            raise ValueError("patch base version mismatch")
        for records in (self.events, self.evidence, self.material_transactions):
            unique(records, "history")
            if any(r.project_id != self.base_plan.project_id for r in records):
                raise ValueError("history project mismatch")
        if tuple(sorted(self.events, key=lambda e: e.recorded_at)) != self.events:
            raise ValueError("events must be chronological")
        return self
