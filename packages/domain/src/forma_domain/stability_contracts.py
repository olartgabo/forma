"""Version-bound modeled stability contracts; these do not establish physical success."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ID, Nonnegative, Record, Text

ContentHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FiniteScalar = Annotated[float, Field(strict=True, allow_inf_nan=False)]
SIUnit = Literal[
    "1", "m", "m2", "m3", "m4", "kg", "s", "rad", "N", "N_m", "Pa", "kg_m3", "m_s2"
]
CheckType = Literal["support", "tip", "slide", "joint", "deformation"]
CheckStatus = Literal[
    "modeled_pass",
    "modeled_fail",
    "indeterminate",
    "needs_measurement",
    "unsupported",
    "not_applicable",
]


class AnalysisIdentity(Record):
    """Exact immutable analysis inputs; hashes are canonical SHA-256 digests.

    Explicit null history_cursor identifies an empty append-only event history.
    Omitting the cursor is invalid; callers must bind even the empty state."""

    project_id: ID
    plan_version_id: ID
    inventory_revision: ID
    history_cursor: ID | None
    operation_state_id: ID
    canonical_geometry_hash: ContentHash
    evidence_hash: ContentHash
    profile_hash: ContentHash


class QuantityEstimate(Record):
    """A scalar, inclusive interval or unknown in an explicit SI unit.

    Dependencies and correlation groups preserve shared uncertainty. Provenance is
    descriptive, never a calibrated confidence probability or physical test result.
    """

    kind: Literal["scalar", "interval", "unknown"]
    unit: SIUnit
    value: FiniteScalar | None = None
    lower: FiniteScalar | None = None
    upper: FiniteScalar | None = None
    provenance: Literal["measured", "specified", "derived", "assumed", "unknown"]
    confirmed: bool
    evidence_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    dependency_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    correlation_group_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    uncertainty_notes: tuple[Text, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def shape(self):
        if self.kind == "scalar":
            valid = self.value is not None and self.lower is None and self.upper is None
        elif self.kind == "interval":
            valid = (
                self.value is None
                and self.lower is not None
                and self.upper is not None
                and self.lower <= self.upper
            )
        else:
            valid = self.value is None and self.lower is None and self.upper is None
        if not valid:
            raise ValueError("quantity must contain exactly its declared value shape")
        if self.kind == "unknown" and (self.confirmed or self.provenance != "unknown"):
            raise ValueError(
                "unknown quantity must remain unconfirmed with unknown provenance"
            )
        if self.kind != "unknown" and self.provenance == "unknown":
            raise ValueError("known quantity requires provenance")
        if self.confirmed and self.provenance in ("assumed", "derived"):
            raise ValueError(
                "assumed or derived quantity cannot claim measurement confirmation"
            )
        if self.provenance == "measured" and not self.evidence_ids:
            raise ValueError("measured quantity requires evidence references")
        return self


class AnalysisPolicy(Record):
    """Caller supplies tolerances and margin; no invented engineering defaults."""

    policy_id: ID
    version: Text
    length_tolerance_m: Nonnegative
    force_tolerance_n: Nonnegative
    moment_tolerance_n_m: Nonnegative
    relative_tolerance: Nonnegative
    required_margin_m: Nonnegative
    uncertainty_method: Literal["analytic_interval", "bounded_subdivision"]
    evaluation_budget: Annotated[int, Field(strict=True, ge=1, le=100000)]
    required_check_types: tuple[CheckType, ...] = Field(min_length=1, max_length=5)
    required_case_ids: tuple[ID, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_requirements(self):
        for values in (self.required_check_types, self.required_case_ids):
            if len(values) != len(set(values)):
                raise ValueError("policy requirements must be unique")
        return self


class CheckResult(Record):
    case_id: ID
    check_type: CheckType
    status: CheckStatus
    computation: Literal[
        "complete", "invalid_input", "numerical_failure", "budget_exhausted", "not_run"
    ]
    explanation: Text
    unresolved_predicates: tuple[Text, ...] = Field(default=(), max_length=128)
    quantities: tuple[QuantityEstimate, ...] = Field(default=(), max_length=128)
    evidence_ids: tuple[ID, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def consistent_status(self):
        if (
            self.status in ("modeled_pass", "modeled_fail")
            and self.computation != "complete"
        ):
            raise ValueError("decisive result requires successful computation")
        if self.status == "modeled_pass" and (
            self.unresolved_predicates
            or any(q.kind == "unknown" for q in self.quantities)
        ):
            raise ValueError("modeled pass cannot contain unresolved inputs")
        if (
            self.computation
            in ("invalid_input", "numerical_failure", "budget_exhausted")
            and self.status != "indeterminate"
        ):
            raise ValueError("failed computation must remain indeterminate")
        if self.status == "not_applicable" and self.computation != "not_run":
            raise ValueError("not-applicable check must not claim computation")
        return self


class StabilityReport(Record):
    """Modeled result only. Physical evidence references confer no physical pass.

    Required coverage is the policy's case/check Cartesian product. Additional
    cases may be reported, but cannot hide an unresolved required check.
    """

    identity: AnalysisIdentity
    report_version: Text
    engine_version: Text
    geometry_version: Text
    profile_version: Text
    cache_hash: ContentHash
    policy: AnalysisPolicy
    status: CheckStatus
    coverage: Literal["complete", "partial", "unsupported"]
    results: tuple[CheckResult, ...] = Field(default=(), max_length=80)
    unresolved_predicates: tuple[Text, ...] = Field(default=(), max_length=128)
    physical_evidence_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    overlays: tuple["StabilityOverlay", ...] = Field(default=(), max_length=16)
    assumption_ids: tuple[ID, ...] = Field(default=(), max_length=16512)
    state_basis: Literal["nominal", "observed"] | None = None
    input_warnings: tuple[Text, ...] = Field(default=(), max_length=288)

    @model_validator(mode="after")
    def aggregate(self):
        indexed = {(r.case_id, r.check_type): r for r in self.results}
        if len(indexed) != len(self.results):
            raise ValueError("duplicate case/check result")
        required = {
            (case, check)
            for case in self.policy.required_case_ids
            for check in self.policy.required_check_types
        }
        if self.coverage == "complete" and not required <= indexed.keys():
            raise ValueError("complete coverage requires every required case/check")
        if self.status == "modeled_pass" and (
            self.coverage != "complete"
            or self.unresolved_predicates
            or any(
                r.status not in ("modeled_pass", "not_applicable") for r in self.results
            )
            or any(indexed[key].status != "modeled_pass" for key in required)
        ):
            raise ValueError("modeled pass requires all required checks to pass")
        if (
            any(
                indexed[key].status == "modeled_fail"
                for key in required & indexed.keys()
            )
            and self.status != "modeled_fail"
        ):
            raise ValueError("required failed check forces aggregate modeled_fail")
        if len({r.case_id for r in self.results}) > 16:
            raise ValueError("at most sixteen cases may be reported")
        if self.status == "modeled_fail" and not any(
            r.status == "modeled_fail" for r in self.results
        ):
            raise ValueError("aggregate fail requires a failed check")
        if self.status == "not_applicable":
            raise ValueError("required analysis cannot be wholly not applicable")
        return self


class Point3(Record):
    """World SI coordinates: right-handed x/y, z upward; never viewer offsets."""

    x: FiniteScalar
    y: FiniteScalar
    z: FiniteScalar


class CenterOfMass(Record):
    x: QuantityEstimate
    y: QuantityEstimate
    z: QuantityEstimate

    @model_validator(mode="after")
    def units(self):
        if any(q.unit != "m" for q in (self.x, self.y, self.z)):
            raise ValueError("world center of mass requires metres")
        return self


class BodyMass(Record):
    body_id: ID
    body_kind: Literal["stand_part", "device"] = "stand_part"
    source_part_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    mass: QuantityEstimate
    center_of_mass: CenterOfMass
    state: Literal["present", "future"] = "present"

    @model_validator(mode="after")
    def positive_mass(self):
        if (self.body_kind == "stand_part" and not self.source_part_ids) or (
            self.body_kind == "device" and self.source_part_ids
        ):
            raise ValueError(
                "stand mass requires source parts; device mass has no stock source parts"
            )
        if len(set(self.source_part_ids)) != len(self.source_part_ids):
            raise ValueError("duplicate mass source part")
        if self.mass.unit != "kg":
            raise ValueError("mass requires kilograms")
        if self.mass.kind == "scalar" and self.mass.value <= 0:
            raise ValueError("known mass must be positive")
        if self.mass.kind == "interval" and self.mass.lower <= 0:
            raise ValueError("mass bounds must be positive")
        return self


class SupportContact(Record):
    contact_id: ID
    body_id: ID
    polygon_world: tuple[Point3, ...] = Field(min_length=3, max_length=128)
    active: bool
    assumption_ids: tuple[ID, ...] = Field(default=(), max_length=128)


def _nonnegative_quantity(quantity, unit, *, positive=False):
    if quantity.unit != unit:
        raise ValueError(f"quantity requires {unit}")
    value = quantity.value if quantity.kind == "scalar" else quantity.lower
    if value is not None and (value < 0 or (positive and value == 0)):
        raise ValueError(
            "quantity must be positive" if positive else "quantity must be nonnegative"
        )


class SlidingDemand(Record):
    """Single contact's supplied reaction demands, not a reaction-force solver."""

    contact_id: ID
    normal_force_n: QuantityEstimate
    tangential_force_n: QuantityEstimate
    friction_coefficient: QuantityEstimate
    planar_coulomb_applicable: bool

    @model_validator(mode="after")
    def units_and_signs(self):
        _nonnegative_quantity(self.normal_force_n, "N")
        _nonnegative_quantity(self.tangential_force_n, "N")
        _nonnegative_quantity(self.friction_coefficient, "1")
        return self


class JointDemand(Record):
    """A named, explicitly supplied scalar failure-mode demand and allowable.

    The stage adapter authenticates joint membership. A comparison does not solve
    load distribution or infer peel, shear, moment and fatigue interaction.
    """

    joint_id: ID
    demand_n: QuantityEstimate
    allowable_n: QuantityEstimate
    capacity_basis: Text
    scalar_mode_applicable: bool

    @model_validator(mode="after")
    def units_and_signs(self):
        _nonnegative_quantity(self.demand_n, "N")
        _nonnegative_quantity(self.allowable_n, "N", positive=True)
        return self


class BeamDeflection(Record):
    """Prismatic Euler-Bernoulli beam; no cardboard shell or buckling inference."""

    member_id: ID
    support_model: Literal["cantilever_end_load", "simply_supported_center_load"]
    force_n: QuantityEstimate
    length_m: QuantityEstimate
    elastic_modulus_pa: QuantityEstimate
    second_moment_m4: QuantityEstimate
    allowable_deflection_m: QuantityEstimate
    linear_elastic_small_deflection_applicable: bool

    @model_validator(mode="after")
    def units_and_signs(self):
        _nonnegative_quantity(self.force_n, "N")
        for quantity, unit in (
            (self.length_m, "m"),
            (self.elastic_modulus_pa, "Pa"),
            (self.second_moment_m4, "m4"),
            (self.allowable_deflection_m, "m"),
        ):
            _nonnegative_quantity(quantity, unit, positive=True)
        return self


class LoadCase(Record):
    case_id: ID
    orientation: Text
    body_ids: tuple[ID, ...] = Field(min_length=1, max_length=64)
    contact_ids: tuple[ID, ...] = Field(max_length=128)
    gravity_m_s2: QuantityEstimate
    sliding: SlidingDemand | None = None
    joint_demands: tuple[JointDemand, ...] = Field(default=(), max_length=16)
    deformation: BeamDeflection | None = None

    @model_validator(mode="after")
    def gravity_and_ids(self):
        if self.gravity_m_s2.unit != "m_s2":
            raise ValueError("gravity requires m_s2")
        for ids in (self.body_ids, self.contact_ids):
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate case reference")
        if len({j.joint_id for j in self.joint_demands}) != len(self.joint_demands):
            raise ValueError("duplicate joint demand")
        if self.sliding is not None and self.sliding.contact_id not in self.contact_ids:
            raise ValueError("sliding contact must belong to the case")
        if self.gravity_m_s2.kind == "scalar" and self.gravity_m_s2.value <= 0:
            raise ValueError("gravity magnitude must be positive")
        if self.gravity_m_s2.kind == "interval" and self.gravity_m_s2.lower <= 0:
            raise ValueError("gravity bounds must be positive")
        return self


class MechanicalSnapshot(Record):
    """Mechanical consumer projection, supplied by the canonical pose producer.

    This is not a scene/pose producer. Nominal and observed are declarations,
    never inferred evidence. Contacts and rigid-body applicability are explicit.
    """

    bodies: tuple[BodyMass, ...] = Field(min_length=1, max_length=64)
    contacts: tuple[SupportContact, ...] = Field(max_length=128)
    rigid_assembly: bool
    horizontal_support: bool
    gravity_only: bool
    state_basis: Literal["nominal", "observed"]
    assumption_ids: tuple[ID, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def references(self):
        bodies = {b.body_id for b in self.bodies}
        if len(bodies) != len(self.bodies):
            raise ValueError("duplicate body ID")
        if len({c.contact_id for c in self.contacts}) != len(self.contacts):
            raise ValueError("duplicate contact ID")
        sources = [p for b in self.bodies for p in b.source_part_ids]
        if len(set(sources)) != len(sources):
            raise ValueError("duplicate mass source contribution")
        if any(c.body_id not in bodies for c in self.contacts):
            raise ValueError("unknown contact body")
        return self


class StabilityInput(Record):
    identity: AnalysisIdentity
    mechanical_snapshot: MechanicalSnapshot
    cases: tuple[LoadCase, ...] = Field(min_length=1, max_length=16)
    geometry_version: Text
    profile_version: Text

    @model_validator(mode="after")
    def references(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("duplicate case ID")
        bodies = {b.body_id for b in self.mechanical_snapshot.bodies}
        contacts = {c.contact_id: c for c in self.mechanical_snapshot.contacts}
        device_ids = {
            b.body_id
            for b in self.mechanical_snapshot.bodies
            if b.body_kind == "device"
        }
        for case in self.cases:
            if len(device_ids.intersection(case.body_ids)) > 1:
                raise ValueError("case permits at most one device")
            if (
                not set(case.body_ids) <= bodies
                or not set(case.contact_ids) <= contacts.keys()
            ):
                raise ValueError("unknown case body/contact")
            if any(contacts[c].body_id not in case.body_ids for c in case.contact_ids):
                raise ValueError("contact body absent from case")
            if case.deformation is not None:
                sources = {
                    p
                    for b in self.mechanical_snapshot.bodies
                    if b.body_id in case.body_ids
                    for p in b.source_part_ids
                }
                if case.deformation.member_id not in sources:
                    raise ValueError(
                        "deformation member must be a source part in the case"
                    )
        return self


class StabilityOverlay(Record):
    """Server-computed modeled geometry only, never physical evidence."""

    case_id: ID
    orientation: Text
    center_of_mass: Point3
    support_polygon: tuple[Point3, ...] = Field(min_length=3, max_length=16384)
    critical_edge: tuple[Point3, ...] = Field(min_length=2, max_length=2)
    signed_margin_m: FiniteScalar
    restoring_moment_n_m: FiniteScalar


StabilityReport.model_rebuild()
