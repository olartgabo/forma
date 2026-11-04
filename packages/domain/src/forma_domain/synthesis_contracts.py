"""Stock-feasible stand design search results (#148).

These records describe bounded, deterministic candidate generation for the one
supported stand family. A candidate is a proposal: it never activates a plan,
consumes stock, records physical work or establishes a physical pass.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ID, Blocker, Positive, Record, Text
from .piece_references import PieceReference

SearchParameter = Literal["part_width_mm", "support_length_mm", "footprint_depth_mm"]
"""Allowlisted design dimensions. The support angle is the user's requirement."""

Millimetres = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Area = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DimensionDomain(Record):
    """A finite step-aligned grid between explicit inclusive bounds.

    Values are ``lower_mm + k * step_mm`` for ``k`` in ``0..count-1``. When the
    bounds are empty the count is zero and ``empty_reason`` names the limiting
    inventory or requirement.
    """

    sheet_stock_id: ID
    parameter: SearchParameter
    unit: Literal["mm"] = "mm"
    step_mm: Millimetres
    lower_mm: float = Field(allow_inf_nan=False)
    upper_mm: float = Field(allow_inf_nan=False)
    count: int = Field(ge=0, le=16)
    lower_basis: Text
    upper_basis: Text
    empty_reason: Text | None = None


class SearchBudget(Record):
    """Node budget is deterministic; the time budget is a guard reported apart."""

    max_nodes: int = Field(default=192, ge=1, le=512)
    max_seconds: float = Field(default=5.0, gt=0, le=20, allow_inf_nan=False)


class StandDesign(Record):
    """Complete identity of one candidate; every value is checked on the server."""

    family: Literal["triangular-tape-stand-v1"] = "triangular-tape-stand-v1"
    sheet_stock_id: ID
    tape_stock_id: ID
    tape_profile_id: ID
    fold_profile_id: ID
    part_width_mm: Millimetres
    support_length_mm: Millimetres
    footprint_depth_mm: Millimetres
    lip_mm: Millimetres
    support_angle_deg: Annotated[float, Field(gt=0, lt=90, allow_inf_nan=False)]


class CandidatePiece(Record):
    """A named canonical piece. Names are engine labels, not observations."""

    piece: PieceReference
    source_stock_id: ID
    source_region_id: ID
    width_mm: Millimetres
    height_mm: Millimetres
    x_mm: float = Field(ge=0, allow_inf_nan=False)
    y_mm: float = Field(ge=0, allow_inf_nan=False)
    dependent: bool
    derivation: Text


class MaterialUse(Record):
    sheet_stock_id: ID
    region_id: ID
    region_area_mm2: Area
    part_area_mm2: Area
    unallocated_area_mm2: Area
    tape_stock_id: ID
    tape_length_mm: Area
    tape_remaining_before_mm: float | None = Field(default=None, allow_inf_nan=False)
    tape_remaining_after_mm: float | None = Field(default=None, allow_inf_nan=False)
    note: Text


CheckStatus = Literal[
    "modeled_pass",
    "modeled_failure",
    "missing_input",
    "unsupported",
    "evidence_incompatible",
    "unverified",
]


class CandidateCheck(Record):
    """One row of the declared check matrix. Unknown is never a pass."""

    check_id: ID
    category: Literal[
        "compiler",
        "geometry",
        "fabrication",
        "access",
        "stability",
        "retention",
        "joint_strength",
    ]
    case_id: ID | None = None
    status: CheckStatus
    detail: Text
    blocker_codes: tuple[Text, ...] = Field(default=(), max_length=16)


class CandidateStep(Record):
    operation_id: ID
    operation_type: Text
    title: Text
    instruction: Text
    part_ids: tuple[ID, ...] = Field(max_length=16)


class CandidateReport(Record):
    candidate_id: ID
    design: StandDesign
    status: Literal["acceptable", "rejected"]
    pieces: tuple[CandidatePiece, ...] = Field(default=(), max_length=8)
    material: MaterialUse | None = None
    checks: tuple[CandidateCheck, ...] = Field(default=(), max_length=32)
    construction: tuple[CandidateStep, ...] = Field(default=(), max_length=16)
    cut_layout_svg: str | None = Field(default=None, max_length=200_000)
    canonical_geometry_hash: Sha256 | None = None
    unresolved: tuple[Text, ...] = Field(default=(), max_length=32)
    blockers: tuple[Blocker, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def acceptable_has_no_hard_failure(self):
        failed = any(check.status == "modeled_failure" for check in self.checks)
        if self.status == "acceptable" and (failed or self.blockers):
            raise ValueError("A candidate with a modeled failure is not acceptable")
        if self.status == "acceptable" and (
            not self.pieces or self.material is None or not self.construction
        ):
            raise ValueError("Acceptable candidates carry pieces, material and steps")
        return self


class SearchIdentity(Record):
    """Every revision the result depends on; a mismatch makes it stale."""

    project_id: ID
    inventory_revision_id: ID
    active_version_id: ID | None
    last_event_id: ID | None
    context_fingerprint: Sha256
    measurement_record_ids: tuple[ID, ...] = Field(max_length=64)
    engine_version: Literal["stand-synthesis-v1"] = "stand-synthesis-v1"


class RejectionCount(Record):
    code: Text
    count: int = Field(ge=1)


class SynthesisResult(Record):
    search_id: Sha256
    identity: SearchIdentity
    status: Literal[
        "candidates_found",
        "infeasible",
        "search_exhausted",
        "needs_input",
        "active_build",
    ]
    budget: SearchBudget
    exhausted: Literal["node_budget", "time_budget"] | None = None
    nodes_evaluated: int = Field(ge=0)
    nodes_total: int = Field(ge=0)
    domains: tuple[DimensionDomain, ...] = Field(default=(), max_length=48)
    candidates: tuple[CandidateReport, ...] = Field(default=(), max_length=2)
    rejections: tuple[RejectionCount, ...] = Field(default=(), max_length=32)
    blockers: tuple[Blocker, ...] = Field(default=(), max_length=32)
    ranking: Text
    limitations: tuple[Text, ...] = Field(max_length=16)
    physical_verification: Literal["not_attempted"] = "not_attempted"

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "candidates_found" and not self.candidates:
            raise ValueError("Found status requires at least one candidate")
        if self.status != "candidates_found" and self.candidates:
            raise ValueError("Only a found search returns candidates")
        if any(c.status != "acceptable" for c in self.candidates):
            raise ValueError("Only acceptable candidates are proposed")
        if self.status == "search_exhausted" and self.exhausted is None:
            raise ValueError("Search exhaustion names the exhausted budget")
        if self.status not in ("candidates_found", "search_exhausted") and (
            self.exhausted is not None
        ):
            raise ValueError("Only a search that ran can exhaust its budget")
        return self


class RepairProbeSummary(Record):
    """Read-only result of the existing repair simulation for an active build."""

    patch_kind: Text
    target_part_id: ID
    status: Text
    preserved_operation_ids: tuple[ID, ...] = Field(max_length=64)
    undo_operation_ids: tuple[ID, ...] = Field(max_length=64)
    recheck_ids: tuple[ID, ...] = Field(max_length=64)
    blockers: tuple[Blocker, ...] = Field(max_length=32)


class ProbeResult(Record):
    search_id: Sha256
    identity: SearchIdentity
    parameter: SearchParameter
    value_mm: Positive
    status: Literal["evaluated", "outside_domain", "requires_repair", "unsupported"]
    base_candidate_id: ID | None = None
    previous_value_mm: float | None = Field(default=None, allow_inf_nan=False)
    report: CandidateReport | None = None
    changed_piece_ids: tuple[ID, ...] = Field(default=(), max_length=8)
    repair: RepairProbeSummary | None = None
    blockers: tuple[Blocker, ...] = Field(default=(), max_length=16)
    physical_verification: Literal["not_attempted"] = "not_attempted"
