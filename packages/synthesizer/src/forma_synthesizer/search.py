"""Bounded deterministic search over the supported triangular tape stand.

Offline only: no provider, HTTP, storage or UI. Every candidate is compiled by
``compile_stand`` (which runs the independent ``validate_plan``), re-rendered by
``render_manual``, projected through the shared canonical geometry producer and
scheduled by the published fabrication report. Nothing here consumes stock,
records physical work or turns an unknown into a pass.
"""

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from forma_compiler import CutProcess
from forma_fabrication import fabrication_report
from forma_renderer import StandParameters, compile_stand, render_manual
from forma_renderer.svg import instruction
from forma_renderer.template import profile_evidence_valid
from forma_stability.geometry import UnsupportedGeometry, project_nominal_geometry
from forma_stability.piece_references import piece_reference

from forma_domain import models as m
from forma_domain.fabrication_contracts import FabricationInput, VersionHistory
from forma_domain.piece_references import PieceReference
from forma_domain.synthesis_contracts import (
    CandidateCheck,
    CandidatePiece,
    CandidateReport,
    CandidateStep,
    DimensionDomain,
    MaterialUse,
    ProbeResult,
    RejectionCount,
    SearchBudget,
    SearchIdentity,
    SearchParameter,
    StandDesign,
    SynthesisResult,
)

ENGINE_VERSION = "stand-synthesis-v1"
GRID_MM = 5.0
MAX_VALUES = 5
MAX_FINALISTS = 8
# Matches the measured point policy's required cases (stability_measurements).
LOAD_CASES = ("portrait", "landscape")
# Candidates are never persisted from a search; selection recompiles with a
# fresh version ID and time. A fixed timestamp keeps identical inputs identical.
CANDIDATE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
PARAMETERS: tuple[SearchParameter, ...] = (
    "part_width_mm",
    "support_length_mm",
    "footprint_depth_mm",
)
# Compiler rejections that ask the user for facts rather than describe the stock.
INPUT_CODES = {"missing_measurement", "needs_confirmation", "unsupported_profile"}
HARD_FABRICATION = {
    "geometry_invalid",
    "stock_exhausted",
    "invalid_order",
    "irreversible_conflict",
    "invalid_reference",
}
RANKING = (
    "Hard failures are excluded. Acceptable designs are ordered by consumed sheet "
    "region area, then total panel area, then the design values. The second "
    "proposal prefers a different sheet, then a different base depth. Unknown "
    "stability, access or cost never counts as zero or as a pass."
)
LIMITATIONS = (
    "Supports only the three-panel triangular tape stand with a folded lip; no other shapes.",
    "Dimensions are design values on a finite grid, not photo measurements.",
    "The support angle is the user's confirmed requirement and is not searched.",
    "A rejection inside this finite grid does not prove that no other layout exists.",
    "No candidate is physically tested; stability for unbuilt geometry needs new measurements.",
)


@dataclass(frozen=True)
class MeasurementBasis:
    """A saved assembled-stand measurement and the geometry it was taken on."""

    record_id: str
    plan_version_id: str
    geometry_basis_hash: str


@dataclass(frozen=True)
class SearchInput:
    """Trusted server-resolved facts. Callers cannot supply stock or evidence."""

    identity: SearchIdentity
    stocks: tuple[m.Stock, ...]
    constraints: m.Constraints | None
    process: CutProcess | None
    parameters: StandParameters | None
    joint_profiles: tuple[m.JointProfile, ...]
    kerf_mm: float | None
    edge_margin_mm: float | None
    declared_tools: tuple[str, ...] | None
    measurements: tuple[MeasurementBasis, ...] = ()
    context_blockers: tuple[m.Blocker, ...] = ()
    # Informational notes on which design settings apply (#149). They never
    # block; the settings fingerprint in ``identity`` already binds them.
    settings_notes: tuple[str, ...] = ()
    # Saved stock left out because the settings in use do not cover it.
    uncovered_stock_ids: tuple[str, ...] = ()
    allow_synthetic: bool = False


@dataclass
class _Compiled:
    design: StandDesign
    plan: m.BuildPlan
    region: m.Region
    key: tuple = field(default=())


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def search_id(data: SearchInput, budget: SearchBudget) -> str:
    """Binds every input revision and the budget; never time or randomness."""
    return _digest(
        {
            "engine": ENGINE_VERSION,
            "identity": data.identity.model_dump(mode="json"),
            "stocks": [s.model_dump(mode="json") for s in data.stocks],
            "constraints": data.constraints.model_dump(mode="json")
            if data.constraints
            else None,
            "process": data.process.model_dump(mode="json") if data.process else None,
            "parameters": data.parameters.model_dump(mode="json")
            if data.parameters
            else None,
            "profiles": [p.model_dump(mode="json") for p in data.joint_profiles],
            "kerf": data.kerf_mm,
            "margin": data.edge_margin_mm,
            "tools": list(data.declared_tools)
            if data.declared_tools is not None
            else None,
            "measurements": [
                [b.record_id, b.plan_version_id, b.geometry_basis_hash]
                for b in data.measurements
            ],
            "context_blockers": [
                b.model_dump(mode="json") for b in data.context_blockers
            ],
            "allow_synthetic": data.allow_synthetic,
            "budget": budget.model_dump(mode="json"),
        }
    )


def candidate_id(design: StandDesign) -> str:
    return "cand-" + _digest(design.model_dump(mode="json"))[:16]


def _known(measurement: m.Measurement | None) -> float | None:
    if measurement is None or measurement.value is None or not measurement.confirmed:
        return None
    return float(measurement.value)


def missing_inputs(data: SearchInput) -> list[m.Blocker]:
    missing = []

    def need(message, *ids, code="missing_measurement"):
        missing.append(m.Blocker(code=code, message=message, target_ids=ids))

    if data.process is None:
        need("Measured cutting process is not configured.")
    elif not data.process.verified(allow_synthetic=data.allow_synthetic):
        need("Cutting process evidence is not verified.", code="unsupported_profile")
    if data.parameters is None:
        need("Confirmed stand parameters are not configured.")
    if data.kerf_mm is None or data.edge_margin_mm is None:
        need("Selected kerf and edge margin are not configured.")
    if data.constraints is None:
        need("Confirm device and space requirements.")
    else:
        for name in (
            "support_angle_deg",
            "max_footprint_width_mm",
            "max_footprint_height_mm",
            "device_mass_g",
        ):
            if _known(getattr(data.constraints, name)) is None:
                need(f"Confirm the {name} requirement.")
        angle = _known(data.constraints.support_angle_deg)
        if angle is not None and not 0 < angle < 90:
            need(
                f"A {angle:g} degree support angle is outside the supported stand "
                "family, which needs an angle strictly between 0 and 90 degrees.",
                code="unsupported",
            )
    if data.parameters is not None:
        if not data.parameters.tools_confirmed:
            need("Confirm suitable cutting tools.", code="needs_confirmation")
        if not data.parameters.joint_access_confirmed:
            need("Confirm access to all three tape hinges.", code="needs_confirmation")
        for name in (
            "lip_mm",
            "device_width_mm",
            "device_contact_height_mm",
            "device_thickness_mm",
            "tape_overlap_mm",
        ):
            if _known(getattr(data.parameters, name)) is None:
                need(f"Confirm {name} before searching.")
    strategies = {p.strategy for p in data.joint_profiles}
    if not {"tape", "fold_brace"} <= strategies:
        need(
            "One reviewed tape profile and one fold profile are required.",
            code="unsupported_profile",
        )
    elif data.parameters is not None and not profile_evidence_valid(
        data.joint_profiles,
        data.parameters.profile_evidence,
        data.identity.project_id,
        allow_synthetic=data.allow_synthetic,
    ):
        need(
            "Joint profiles need user-observed physical test evidence.",
            code="unsupported_profile",
        )
    missing.extend(data.context_blockers)
    return missing


def _grid(lower: float, upper: float) -> tuple[float, float, int]:
    lower = math.ceil(lower / GRID_MM - 1e-9) * GRID_MM
    upper = math.floor(upper / GRID_MM + 1e-9) * GRID_MM
    if upper < lower:
        return lower, upper, 0
    span = upper - lower
    step = GRID_MM
    if span / step > MAX_VALUES - 1:
        step = math.ceil(span / (MAX_VALUES - 1) / GRID_MM - 1e-9) * GRID_MM
    return lower, step, int(span // step) + 1


def domains_for(data: SearchInput, sheet: m.Stock) -> tuple[DimensionDomain, ...]:
    """Three finite grids for one sheet, bounded by measurements and limits."""
    p, c = data.parameters, data.constraints
    margin = float(data.edge_margin_mm)
    region = sheet.usable_regions[0].geometry
    angle = math.radians(c.support_angle_deg.value)
    lip = p.lip_mm.value
    rows = (
        (
            "part_width_mm",
            p.device_width_mm.value,
            "confirmed device width",
            min(region.width - 2 * margin, c.max_footprint_width_mm.value),
            f"min(sheet usable width {region.width:g} mm minus two {margin:g} mm margins, "
            f"maximum footprint width {c.max_footprint_width_mm.value:g} mm)",
        ),
        (
            "support_length_mm",
            p.device_contact_height_mm.value,
            "confirmed device contact height",
            region.height - 2 * margin - lip,
            f"sheet usable height {region.height:g} mm minus margins and the {lip:g} mm lip",
        ),
        (
            "footprint_depth_mm",
            p.device_contact_height_mm.value * math.cos(angle) + GRID_MM,
            "horizontal reach of the shortest support plus one grid step",
            c.max_footprint_height_mm.value,
            f"maximum footprint depth {c.max_footprint_height_mm.value:g} mm",
        ),
    )
    result = []
    for parameter, lower, lower_basis, upper, upper_basis in rows:
        start, step, count = _grid(lower, upper)
        result.append(
            DimensionDomain(
                sheet_stock_id=sheet.id,
                parameter=parameter,
                step_mm=step if count else GRID_MM,
                lower_mm=start,
                upper_mm=start + step * (count - 1) if count else upper,
                count=count,
                lower_basis=lower_basis,
                upper_basis=upper_basis,
                empty_reason=None
                if count
                else f"Stock {sheet.id} is too small: {upper_basis} is below the {lower_basis} ({lower:g} mm).",
            )
        )
    return tuple(result)


def domain_values(domain: DimensionDomain) -> tuple[float, ...]:
    return tuple(
        round(domain.lower_mm + k * domain.step_mm, 6) for k in range(domain.count)
    )


def _sheets(data: SearchInput, rejections: dict[str, int]) -> list[m.Stock]:
    sheets = []
    for stock in sorted(data.stocks, key=lambda s: s.id):
        if stock.kind != "sheet":
            continue
        if (
            len(stock.usable_regions) != 1
            or stock.usable_regions[0].geometry.rotation_deg != 0
        ):
            rejections["unsupported_stock_layout"] = (
                rejections.get("unsupported_stock_layout", 0) + 1
            )
            continue
        sheets.append(stock)
    return sheets


def _profile_pairs(data: SearchInput):
    tapes = sorted(p.id for p in data.joint_profiles if p.strategy == "tape")
    folds = sorted(p.id for p in data.joint_profiles if p.strategy == "fold_brace")
    return [(t, f) for t in tapes for f in folds]


def _compile(data: SearchInput, design: StandDesign) -> m.CompilerResult:
    candidate = design_candidate(design)
    request = m.CompilerInput(
        project_id=data.identity.project_id,
        version_id=candidate.id,
        created_at=CANDIDATE_TIME,
        candidate=candidate,
        stocks=data.stocks,
        joint_profiles=data.joint_profiles,
        constraints=data.constraints.model_copy(
            update={"allowed_profile_ids": tuple(p.id for p in data.joint_profiles)}
        ),
        kerf_mm=data.kerf_mm,
        edge_margin_mm=data.edge_margin_mm,
        process_evidence_ids=tuple(e.id for e in data.process.evidence),
    )
    return compile_stand(
        request,
        stand_parameters(data.parameters, design),
        process=data.process,
        allow_synthetic=data.allow_synthetic,
    )


def stand_parameters(base: StandParameters, design: StandDesign) -> StandParameters:
    """The search chooses base depth; every device measurement stays the user's."""
    return base.model_copy(
        update={
            "footprint_depth_mm": m.Measurement(
                value=design.footprint_depth_mm,
                unit="mm",
                source="calculated",
                confirmed=True,
            )
        }
    )


def design_candidate(design: StandDesign) -> m.DesignCandidate:
    """The DesignCandidate the existing preview transaction compiles."""
    return m.DesignCandidate(
        id=candidate_id(design),
        family="tabletop_fixture_v1",
        support_angle_deg=design.support_angle_deg,
        part_width_mm=design.part_width_mm,
        part_height_mm=design.support_length_mm + design.lip_mm,
        panel_count=3,
        stock_ids=(design.sheet_stock_id, design.tape_stock_id),
        profile_ids=(design.tape_profile_id, design.fold_profile_id),
        assumptions=("Engine-generated design values on a finite search grid.",),
    )


PIECES = {
    "stand-support": ("Support panel", "Holds the device; its top folds into the lip"),
    "stand-base": ("Base panel", "Rests on the table"),
    "stand-brace": ("Rear brace", "Closes the triangle behind the support"),
}
TITLES = {
    "cut_rect": "Cut the panels",
    "inspect": "Check",
    "fold": "Fold the lip",
    "tape_joint": "Tape a hinge",
    "functional_test": "Test with the device",
}


def _pieces(plan: m.BuildPlan, design: StandDesign) -> tuple[CandidatePiece, ...]:
    angle = math.radians(design.support_angle_deg)
    reach = design.support_length_mm * math.cos(angle)
    rise = design.support_length_mm * math.sin(angle)
    derivations = {
        "stand-support": f"Support {design.support_length_mm:g} mm plus {design.lip_mm:g} mm lip",
        "stand-base": f"Base depth {design.footprint_depth_mm:g} mm",
        "stand-brace": (
            f"Derived: sqrt(({design.footprint_depth_mm:g} - {reach:.2f})^2 + {rise:.2f}^2) "
            f"from support, angle {design.support_angle_deg:g} deg and base depth"
        ),
    }
    pieces = []
    for part in plan.parts:
        name, role = PIECES[part.id]
        pieces.append(
            CandidatePiece(
                piece=PieceReference(
                    part_id=part.id,
                    reference=piece_reference(part.id),
                    display_name=name,
                    geometry_class="rectangle",
                    role=role,
                ),
                source_stock_id=part.source_stock_id,
                source_region_id=part.source_region_id,
                width_mm=part.geometry.width,
                height_mm=part.geometry.height,
                x_mm=part.geometry.x,
                y_mm=part.geometry.y,
                dependent=part.id == "stand-brace",
                derivation=derivations[part.id],
            )
        )
    return tuple(pieces)


def _material(plan: m.BuildPlan, design: StandDesign, region: m.Region, stocks):
    tape = next(s for s in stocks if s.id == design.tape_stock_id)
    length = sum(op.args.length_mm for op in plan.operations if op.type == "tape_joint")
    before = _known(tape.remaining_length_mm)
    part_area = sum(p.geometry.width * p.geometry.height for p in plan.parts)
    region_area = region.geometry.width * region.geometry.height
    return MaterialUse(
        sheet_stock_id=design.sheet_stock_id,
        region_id=region.id,
        region_area_mm2=region_area,
        part_area_mm2=part_area,
        unallocated_area_mm2=max(region_area - part_area, 0.0),
        tape_stock_id=tape.id,
        tape_length_mm=length,
        tape_remaining_before_mm=before,
        tape_remaining_after_mm=None if before is None else before - length,
        note=(
            "The template consumes the whole region; unallocated area is waste, "
            "not a reusable offcut. Proposals consume nothing until work is reported."
        ),
    )


def _stability_rows(data: SearchInput, geometry_hash: str | None):
    rows = []
    for case in LOAD_CASES:
        if data.measurements:
            used = ", ".join(
                f"{b.record_id} (plan {b.plan_version_id})" for b in data.measurements
            )
            rows.append(
                CandidateCheck(
                    check_id=f"stability-tip-{case}",
                    category="stability",
                    case_id=case,
                    status="evidence_incompatible",
                    detail=(
                        f"Saved measurements {used} describe another assembled geometry. "
                        f"This unbuilt candidate ({(geometry_hash or 'no geometry')[:12]}) "
                        "needs its own assembled-stand and device measurements."
                    ),
                )
            )
        else:
            rows.append(
                CandidateCheck(
                    check_id=f"stability-tip-{case}",
                    category="stability",
                    case_id=case,
                    status="missing_input",
                    detail=(
                        f"Tipping ({case}) needs measured assembled-stand mass and centre of "
                        "mass, device centre of mass and pose, and actual contact; none exist "
                        "for this unbuilt geometry."
                    ),
                )
            )
        rows.append(
            CandidateCheck(
                check_id=f"retention-{case}",
                category="retention",
                case_id=case,
                status="unsupported",
                detail="Device retention and sliding have no supported model; a tipping result would not cover them.",
            )
        )
    rows.append(
        CandidateCheck(
            check_id="joint-strength",
            category="joint_strength",
            status="unsupported",
            detail="Tape hinge strength and cardboard deformation are not modeled.",
        )
    )
    return rows


def _fabrication_rows(data: SearchInput, plan: m.BuildPlan):
    report = fabrication_report(
        FabricationInput(
            project_id=data.identity.project_id,
            inventory_revision_id=data.identity.inventory_revision_id,
            lineage=(VersionHistory(plan=plan),),
            remaining_stock=data.stocks,
            declared_tools=data.declared_tools,
            context_blockers=data.context_blockers,
            profile_evidence=data.parameters.profile_evidence,
        ),
        process=data.process,
        allow_synthetic=data.allow_synthetic,
    )
    blockers = list(report.blockers) + [
        b for op in report.operations for b in op.blockers
    ]
    codes = tuple(dict.fromkeys(b.code for b in blockers))[:16]
    if report.status == "ready" and report.order_status == "complete":
        fabrication = CandidateCheck(
            check_id="fabrication-order",
            category="fabrication",
            status="modeled_pass",
            detail="The published fabrication rules (declared tools and order) schedule every step.",
        )
    elif report.order_status == "cycle" or any(
        # Per-step waits and missing tool declarations are unresolved inputs;
        # only plan-level compiler blockers are hard failures.
        b.code in HARD_FABRICATION
        for b in report.blockers
    ):
        fabrication = CandidateCheck(
            check_id="fabrication-order",
            category="fabrication",
            status="modeled_failure",
            detail="; ".join(dict.fromkeys(b.message for b in blockers))[:2000],
            blocker_codes=codes,
        )
    else:
        fabrication = CandidateCheck(
            check_id="fabrication-order",
            category="fabrication",
            status="missing_input",
            detail=(
                "; ".join(dict.fromkeys(b.message for b in blockers))
                or "Fabrication order is incomplete."
            )[:2000],
            blocker_codes=codes,
        )
    access = CandidateCheck(
        check_id="fabrication-access",
        category="access",
        status="unverified",
        detail="Hinge access follows declared rules only; observed usability is not assessed.",
    )
    return [fabrication, access]


def evaluate(data: SearchInput, design: StandDesign) -> CandidateReport:
    """Compile, render, project and schedule one design. Pure and repeatable."""
    cid = candidate_id(design)
    compiled = _compile(data, design)
    if compiled.status != "accepted":
        return CandidateReport(
            candidate_id=cid,
            design=design,
            status="rejected",
            checks=(
                CandidateCheck(
                    check_id="compiler",
                    category="compiler",
                    status="missing_input"
                    if compiled.status == "needs_measurement"
                    else "modeled_failure",
                    detail="; ".join(b.message for b in compiled.blockers)[:2000],
                    blocker_codes=tuple(b.code for b in compiled.blockers)[:16],
                ),
            ),
            blockers=compiled.blockers[:16],
        )
    plan = compiled.plan
    manual = render_manual(
        plan,
        process=data.process,
        profile_evidence=data.parameters.profile_evidence,
        allow_synthetic=data.allow_synthetic,
    )
    if manual.status != "accepted":
        return CandidateReport(
            candidate_id=cid,
            design=design,
            status="rejected",
            checks=(
                CandidateCheck(
                    check_id="manual",
                    category="compiler",
                    status="modeled_failure",
                    detail="; ".join(b.message for b in manual.blockers)[:2000],
                    blocker_codes=tuple(b.code for b in manual.blockers)[:16],
                ),
            ),
            blockers=manual.blockers[:16],
        )
    checks = [
        CandidateCheck(
            check_id="compiler",
            category="compiler",
            status="modeled_pass",
            detail="compile_stand, the independent plan validator and the manual renderer accepted the stock allocation and geometry.",
        )
    ]
    blockers: list[m.Blocker] = []
    geometry_hash = None
    try:
        geometry = project_nominal_geometry(plan)
        geometry_hash = geometry.geometry_hash
        checks.append(
            CandidateCheck(
                check_id="canonical-geometry",
                category="geometry",
                status="modeled_pass",
                detail="Shared nominal geometry regenerated for support, base and brace; it is nominal, not observed contact.",
            )
        )
    except UnsupportedGeometry as error:
        message = str(error)[:2000]
        checks.append(
            CandidateCheck(
                check_id="canonical-geometry",
                category="geometry",
                status="modeled_failure",
                detail=message,
                blocker_codes=("unsupported",),
            )
        )
        blockers.append(m.Blocker(code="unsupported", message=message))
    checks.extend(_fabrication_rows(data, plan))
    checks.extend(_stability_rows(data, geometry_hash))
    region = next(
        s for s in data.stocks if s.id == design.sheet_stock_id
    ).usable_regions[0]
    operations = {op.id: op for op in plan.operations}
    steps = tuple(
        CandidateStep(
            operation_id=panel.operation_id,
            operation_type=operations[panel.operation_id].type,
            title=TITLES.get(operations[panel.operation_id].type, "Step"),
            instruction=instruction(operations[panel.operation_id], plan)[:2000],
            part_ids=panel.part_ids,
        )
        for panel in manual.panels
    )
    cut = next(
        (p.svg for p in manual.panels if p.operation_id == "stand-cut-panels"), None
    )
    failed = any(c.status == "modeled_failure" for c in checks)
    return CandidateReport(
        candidate_id=cid,
        design=design,
        status="rejected" if failed or blockers else "acceptable",
        pieces=_pieces(plan, design),
        material=_material(plan, design, region, data.stocks),
        checks=tuple(checks),
        construction=steps,
        cut_layout_svg=cut,
        canonical_geometry_hash=geometry_hash,
        unresolved=tuple(
            f"{c.check_id}: {c.status.replace('_', ' ')}"
            for c in checks
            if c.status != "modeled_pass"
        ),
        blockers=tuple(blockers),
    )


def _identity_result(data, budget, **values) -> SynthesisResult:
    return SynthesisResult(
        search_id=search_id(data, budget),
        identity=data.identity,
        budget=budget,
        ranking=RANKING,
        limitations=LIMITATIONS,
        **values,
    )


def search(
    data: SearchInput,
    budget: SearchBudget | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> SynthesisResult:
    budget = budget or SearchBudget()
    started = clock()
    if data.identity.active_version_id is not None:
        return _identity_result(
            data,
            budget,
            status="active_build",
            nodes_evaluated=0,
            nodes_total=0,
            blockers=(
                m.Blocker(
                    code="irreversible_conflict",
                    message="A build is active. Fresh designs cannot replace it; use a probe, which runs the existing repair simulation.",
                ),
            ),
        )
    missing = missing_inputs(data)
    if missing:
        return _identity_result(
            data,
            budget,
            status="needs_input",
            nodes_evaluated=0,
            nodes_total=0,
            blockers=tuple(missing[:32]),
        )
    rejections: dict[str, int] = {}
    sheets = _sheets(data, rejections)
    tape_stock = sorted(
        (s for s in data.stocks if s.kind == "tape"), key=lambda s: s.id
    )

    def sheet_known(s):
        return None not in (
            _known(s.width_mm),
            _known(s.height_mm),
            _known(s.thickness_mm),
        )

    def tape_known(s):
        return None not in (_known(s.width_mm), _known(s.remaining_length_mm))

    measured = [s for s in sheets if sheet_known(s)]
    tapes = [s for s in tape_stock if tape_known(s)]
    unmeasured = [
        m.Blocker(
            code="missing_measurement",
            message=f"Measure stock {s.id}; unknown dimensions are never assumed.",
            target_ids=(s.id,),
        )
        for s in sheets + tape_stock
        if s not in measured and s not in tapes
    ]
    if not measured or not tapes:
        return _identity_result(
            data,
            budget,
            status="needs_input",
            nodes_evaluated=0,
            nodes_total=0,
            blockers=tuple(
                unmeasured
                or [
                    m.Blocker(
                        code="stock_exhausted",
                        message="No measured single-region sheet and measured tape are saved.",
                    )
                ]
            )[:32],
        )
    angle = float(data.constraints.support_angle_deg.value)
    lip = float(data.parameters.lip_mm.value)
    pairs = _profile_pairs(data)
    grids = []
    for sheet in measured:
        domains = domains_for(data, sheet)
        grids.append((sheet, domains, tuple(domain_values(d) for d in domains)))
    all_domains = [d for _, domains, _ in grids for d in domains]
    nodes_total = sum(
        len(tapes) * len(pairs) * len(w) * len(s) * len(d) for _, _, (w, s, d) in grids
    )

    def space():
        # Lazy: the budget bounds work, not just the reported node count.
        for sheet, _, (widths, supports, depths) in grids:
            for tape in tapes:
                for tape_profile, fold_profile in pairs:
                    for width in widths:
                        for support in supports:
                            for depth in depths:
                                yield StandDesign(
                                    sheet_stock_id=sheet.id,
                                    tape_stock_id=tape.id,
                                    tape_profile_id=tape_profile,
                                    fold_profile_id=fold_profile,
                                    part_width_mm=width,
                                    support_length_mm=support,
                                    footprint_depth_mm=depth,
                                    lip_mm=lip,
                                    support_angle_deg=angle,
                                )

    exhausted = None
    accepted: list[_Compiled] = []
    evaluated = 0
    input_blockers: dict[str, m.Blocker] = {}
    for design in space():
        if evaluated >= budget.max_nodes:
            exhausted = "node_budget"
            break
        if clock() - started > budget.max_seconds:
            exhausted = "time_budget"
            break
        evaluated += 1
        result = _compile(data, design)
        if result.status != "accepted":
            for blocker in result.blockers:
                if blocker.code in INPUT_CODES:
                    input_blockers.setdefault(blocker.code, blocker)
            for code in {b.code for b in result.blockers} or {"blocked"}:
                rejections[code] = rejections.get(code, 0) + 1
            continue
        region = next(
            s for s in measured if s.id == design.sheet_stock_id
        ).usable_regions[0]
        area = sum(p.geometry.width * p.geometry.height for p in result.plan.parts)
        accepted.append(
            _Compiled(
                design=design,
                plan=result.plan,
                region=region,
                key=(
                    region.geometry.width * region.geometry.height,
                    round(area, 6),
                    json.dumps(design.model_dump(mode="json"), sort_keys=True),
                ),
            )
        )
    accepted.sort(key=lambda item: item.key)
    chosen: list[CandidateReport] = []
    finalists = 0
    for item in accepted:
        if finalists >= MAX_FINALISTS or len(chosen) == 2:
            break
        if chosen and not _prefer_second(chosen[0].design, item.design, accepted):
            continue
        if clock() - started > budget.max_seconds:
            exhausted = "time_budget"
            break
        finalists += 1
        report = evaluate(data, item.design)
        if report.status == "acceptable":
            chosen.append(report)
        else:
            for check in report.checks:
                if check.status == "modeled_failure":
                    for code in check.blocker_codes or ("modeled_failure",):
                        rejections[code] = rejections.get(code, 0) + 1
    if chosen:
        status = "candidates_found"
    elif exhausted:
        status = "search_exhausted"
    elif input_blockers:
        # The compiler asked for a measurement or confirmation; that is not
        # evidence that the stock cannot make the stand.
        status = "needs_input"
    else:
        status = "infeasible"
    empty = [
        m.Blocker(
            code="stock_exhausted",
            message=d.empty_reason,
            target_ids=(d.sheet_stock_id,),
        )
        for d in all_domains
        if d.empty_reason
    ]
    return _identity_result(
        data,
        budget,
        status=status,
        exhausted=exhausted,
        nodes_evaluated=evaluated,
        nodes_total=nodes_total,
        domains=tuple(all_domains[:48]),
        candidates=tuple(chosen),
        rejections=tuple(
            RejectionCount(code=code, count=count)
            for code, count in sorted(rejections.items())
        )[:32],
        blockers=tuple(
            unmeasured
            + (list(input_blockers.values()) if status == "needs_input" else [])
            + (empty if status != "candidates_found" else [])
        )[:32],
    )


def _prefer_second(first: StandDesign, other: StandDesign, accepted) -> bool:
    """Diversity tiers: another sheet, else another base depth, else any."""
    designs = [a.design for a in accepted]
    if any(d.sheet_stock_id != first.sheet_stock_id for d in designs):
        return other.sheet_stock_id != first.sheet_stock_id
    if any(d.footprint_depth_mm != first.footprint_depth_mm for d in designs):
        return other.footprint_depth_mm != first.footprint_depth_mm
    return other != first


def check_design(data: SearchInput, design: StandDesign) -> list[m.Blocker]:
    """Every value must come from the server's finite domains and saved records."""
    problems = []

    def bad(message, code="invalid_reference"):
        problems.append(m.Blocker(code=code, message=message))

    sheets = {s.id: s for s in _sheets(data, {})}
    tapes = {s.id for s in data.stocks if s.kind == "tape"}
    if design.sheet_stock_id not in sheets:
        bad("The design names a sheet that is not a saved single-region sheet.")
    if design.tape_stock_id not in tapes:
        bad("The design names tape that is not saved.")
    if (design.tape_profile_id, design.fold_profile_id) not in _profile_pairs(data):
        bad("The design names joint profiles that are not reviewed for this revision.")
    if design.lip_mm != data.parameters.lip_mm.value:
        bad("The lip comes from the confirmed stand parameters.")
    if design.support_angle_deg != data.constraints.support_angle_deg.value:
        bad("The support angle is the confirmed requirement.")
    if problems:
        return problems
    for domain in domains_for(data, sheets[design.sheet_stock_id]):
        if getattr(design, domain.parameter) not in domain_values(domain):
            bad(
                f"{domain.parameter} = {getattr(design, domain.parameter):g} mm is outside its finite domain.",
                code="unsupported",
            )
    return problems


def probe(
    data: SearchInput,
    budget: SearchBudget,
    base: StandDesign,
    parameter: SearchParameter,
    value_mm: float,
) -> ProbeResult:
    """Change one allowlisted dimension, recompile everything that depends on it."""
    fields = dict(
        search_id=search_id(data, budget),
        identity=data.identity,
        parameter=parameter,
        value_mm=value_mm,
        base_candidate_id=candidate_id(base),
        previous_value_mm=getattr(base, parameter),
    )
    missing = missing_inputs(data)
    if missing:
        return ProbeResult(**fields, status="unsupported", blockers=tuple(missing[:16]))
    base_problems = check_design(data, base)
    if base_problems:
        return ProbeResult(
            **fields, status="outside_domain", blockers=tuple(base_problems[:16])
        )
    changed = base.model_copy(update={parameter: value_mm})
    problems = check_design(data, changed)
    if problems:
        return ProbeResult(
            **fields, status="outside_domain", blockers=tuple(problems[:16])
        )
    before = evaluate(data, base)
    after = evaluate(data, changed)
    old = {p.piece.part_id: (p.width_mm, p.height_mm) for p in before.pieces}
    moved = tuple(
        p.piece.part_id
        for p in after.pieces
        if old.get(p.piece.part_id) != (p.width_mm, p.height_mm)
    )
    return ProbeResult(
        **fields, status="evaluated", report=after, changed_piece_ids=moved
    )
