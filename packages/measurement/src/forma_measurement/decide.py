"""Deterministic measurement decisions over authorized design and stability facts.

Offline only. The rule asks for a measurement only when a confirmed value can
change a supported decision: whether a saved sheet or tape can be used by the
stand search (thresholds found by the compiler itself), or whether a built
stand's modeled tipping result can be computed. It never confirms a value,
uses an estimate as a fact, approves a design or records physical work.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from forma_renderer import compile_stand
from forma_stability.piece_references import piece_reference
from forma_synthesizer import (
    SearchInput,
    design_candidate,
    domain_values,
    domains_for,
    stand_parameters,
)
from forma_synthesizer.search import CANDIDATE_TIME, INPUT_CODES

from forma_domain import models as m
from forma_domain.measurement_contracts import (
    CurrentValue,
    DecisionChange,
    DecisionIdentity,
    DecisionThreshold,
    DesignSummary,
    MeasurementDecision,
    MeasurementQuestion,
    MeasurementTarget,
    SavedFact,
    StabilitySummary,
)
from forma_domain.piece_references import PieceReference
from forma_domain.synthesis_contracts import StandDesign, SynthesisResult

PROBE_MM = 5000
SHEET_PROPERTIES = ("thickness_mm", "width_mm", "height_mm")
TAPE_PROPERTIES = ("width_mm", "remaining_length_mm")
REQUIREMENTS = (
    ("device_mass_g", "g", "Device mass"),
    ("support_angle_deg", "deg", "Support angle"),
    ("max_footprint_width_mm", "mm", "Maximum footprint width"),
    ("max_footprint_height_mm", "mm", "Maximum footprint depth"),
)
SELECTION_RULE = (
    "Ask only for a confirmed value that can change a supported decision. Order: "
    "missing build requirements, then tape when no confirmed tape is usable, then "
    "sheets (thickness, width, height, usable area), each by stock ID. Skip stock "
    "already confirmed outside a compiler threshold, values the user marked "
    "unavailable, and kinds the stand cannot use. Estimates are never used as "
    "values. One question at a time; no probabilities or effort scores."
)
STABILITY_GAP = (
    "No model predicts an unbuilt design's assembled mass, centre of mass or support "
    "contact. Measurements of a built stand describe that stand only and do not "
    "transfer to other geometry."
)
RETENTION_GAP = (
    "Phone retention, sliding and tape joint strength have no supported model."
)
SETTINGS_GAP = (
    "Server design settings (cutting process, stand parameters and reviewed "
    "profiles) are reviewed for an inventory revision. Settings from an earlier "
    "revision are reused only for the same stock items with only measured values "
    "changed; here none could be reused, so the operator must add settings."
)
PIECES = {
    "stand-support": "Support panel",
    "stand-base": "Base panel",
    "stand-brace": "Rear brace",
}


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _confirmed(measurement: m.Measurement | None) -> float | None:
    if measurement is None or measurement.value is None or not measurement.confirmed:
        return None
    return float(measurement.value)


def _current(measurement: m.Measurement) -> CurrentValue:
    return CurrentValue(
        value=measurement.value,
        unit=measurement.unit,
        source=measurement.source,
        confirmed=measurement.confirmed,
    )


@dataclass(frozen=True)
class Thresholds:
    """Smallest stock of one material that admits the smallest searched design.

    ``width_mm`` and ``height_mm`` are found in 0.1 mm steps. A confirmed value
    below them is still checked against the compiler directly with ``fits``, so
    a rounded threshold never excludes stock on its own.
    """

    material: str
    design: StandDesign
    width_mm: float
    height_mm: float
    tape_width_mm: float
    tape_length_mm: float
    thickness_ranges: tuple[tuple[float, float], ...]
    fits: Callable[..., bool] = field(compare=False, repr=False)


@dataclass(frozen=True)
class Blocked:
    """Why a sheet material has no threshold.

    ``no_profiles``: no reviewed tape and fold pair covers the material.
    ``needs_input``: the compiler refused unlimited, confirmed stock for an
    input reason (for example missing profile evidence) that no stock size can
    supply. ``infeasible``: even unlimited stock cannot make the smallest stand.
    """

    material: str
    kind: Literal["no_profiles", "needs_input", "infeasible"]
    reasons: tuple[str, ...]


def _compile(data: SearchInput, design: StandDesign) -> m.CompilerResult:
    request = m.CompilerInput(
        project_id=data.identity.project_id,
        version_id="measurement-threshold-probe",
        created_at=CANDIDATE_TIME,
        candidate=design_candidate(design),
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


def _measured(value: float, unit="mm") -> m.Measurement:
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def _probe_sheet(material: str, thickness: float, width: float, height: float):
    """A hypothetical sheet used only to locate thresholds; never a candidate."""
    return m.Stock(
        id="threshold-probe-sheet",
        kind="sheet",
        material=material,
        condition="usable",
        width_mm=_measured(width),
        height_mm=_measured(height),
        thickness_mm=_measured(thickness),
        remaining_length_mm=m.Measurement(
            value=None, unit="mm", source="unknown", confirmed=False
        ),
        usable_regions=(
            m.Region(
                id="threshold-probe-region",
                geometry=m.Rect(x=0, y=0, width=width, height=height),
            ),
        ),
    )


def _probe_tape() -> m.Stock:
    return m.Stock(
        id="threshold-probe-tape",
        kind="tape",
        material="other_supported",
        condition="usable",
        width_mm=_measured(PROBE_MM),
        height_mm=m.Measurement(
            value=None, unit="mm", source="unknown", confirmed=False
        ),
        thickness_mm=m.Measurement(
            value=None, unit="mm", source="unknown", confirmed=False
        ),
        remaining_length_mm=_measured(PROBE_MM * 10),
    )


def thickness_ranges(
    data: SearchInput, material: str = "cardboard"
) -> tuple[tuple[float, float], ...]:
    """Thicknesses accepted by both profiles of a reviewed pair for ``material``."""
    profiles = {p.id: p for p in data.joint_profiles}
    ranges = []
    for tape in sorted(p for p in profiles if profiles[p].strategy == "tape"):
        for fold in sorted(p for p in profiles if profiles[p].strategy == "fold_brace"):
            pair = (profiles[tape], profiles[fold])
            if any(
                p.thickness_min_mm is None
                or p.thickness_max_mm is None
                or p.material != material
                for p in pair
            ):
                continue
            low = max(p.thickness_min_mm for p in pair)
            high = min(p.thickness_max_mm for p in pair)
            if low <= high:
                ranges.append((low, high))
    return tuple(sorted(set(ranges)))


def profile_materials(data: SearchInput) -> tuple[str, ...]:
    """Sheet materials covered by at least one reviewed tape and fold pair."""
    return tuple(
        sorted(
            {
                p.material
                for p in data.joint_profiles
                if thickness_ranges(data, p.material)
            }
        )
    )


def thresholds(data: SearchInput, material: str = "cardboard") -> Thresholds | Blocked:
    """Compiler thresholds for one sheet material, or why there are none."""
    ranges = thickness_ranges(data, material)
    if not ranges:
        return Blocked(
            material,
            "no_profiles",
            (
                f"No reviewed tape and fold profile pair covers {material} sheets. "
                "Reviewed profiles for this material are server design context, "
                "not a measurement.",
            ),
        )
    default_thickness = (ranges[0][0] + ranges[0][1]) / 2
    tape_profiles = sorted(p.id for p in data.joint_profiles if p.strategy == "tape")
    fold_profiles = sorted(
        p.id for p in data.joint_profiles if p.strategy == "fold_brace"
    )

    def with_sheet(width, height, thickness=None):
        sheet = _probe_sheet(
            material,
            default_thickness if thickness is None else thickness,
            width,
            height,
        )
        return replace(data, stocks=(sheet, _probe_tape())), sheet

    big, sheet = with_sheet(PROBE_MM, PROBE_MM)
    widths, supports, depths = (domain_values(d) for d in domains_for(big, sheet))
    unlimited = (
        f"Even unlimited {material} stock cannot make the smallest supported stand "
        "within the confirmed requirements and device sizes.",
    )
    if not widths or not supports:
        return Blocked(material, "infeasible", unlimited)

    needs: dict[str, str] = {}

    def smallest_design():
        # The first grid design (smallest width and support, shallowest base)
        # that compiles on unlimited stock, in the search's own order.
        for depth in depths:
            for tape_profile in tape_profiles:
                for fold_profile in fold_profiles:
                    design = StandDesign(
                        sheet_stock_id=sheet.id,
                        tape_stock_id="threshold-probe-tape",
                        tape_profile_id=tape_profile,
                        fold_profile_id=fold_profile,
                        part_width_mm=widths[0],
                        support_length_mm=supports[0],
                        footprint_depth_mm=depth,
                        lip_mm=float(data.parameters.lip_mm.value),
                        support_angle_deg=float(
                            data.constraints.support_angle_deg.value
                        ),
                    )
                    result = _compile(big, design)
                    if result.status == "accepted":
                        return design, result
                    for blocker in result.blockers:
                        if blocker.code in INPUT_CODES:
                            needs.setdefault(blocker.code, blocker.message)
        return None

    found = smallest_design()
    if found is None:
        # Unlimited, fully confirmed stock was refused for an input reason:
        # a missing input, not proof that no stock can work.
        if needs:
            return Blocked(
                material, "needs_input", tuple(needs[c] for c in sorted(needs))
            )
        return Blocked(material, "infeasible", unlimited)
    design, result = found
    cache: dict[tuple, bool] = {}

    def fits(width, height, thickness=None) -> bool:
        key = (float(width), float(height), thickness)
        if key not in cache:
            probe, _ = with_sheet(width, height, thickness)
            cache[key] = _compile(probe, design).status == "accepted"
        return cache[key]

    def smallest(accepts) -> float:
        # Tenths of a millimetre; the upper bound is known to compile.
        low, high = 1, PROBE_MM * 10
        while low < high:
            middle = (low + high) // 2
            if accepts(middle / 10):
                high = middle
            else:
                low = middle + 1
        return low / 10

    tape_length = sum(
        op.args.length_mm for op in result.plan.operations if op.type == "tape_joint"
    )
    return Thresholds(
        material=material,
        design=design,
        width_mm=smallest(lambda w: fits(w, PROBE_MM)),
        height_mm=smallest(lambda h: fits(PROBE_MM, h)),
        tape_width_mm=2 * float(data.parameters.tape_overlap_mm.value),
        tape_length_mm=float(tape_length),
        thickness_ranges=ranges,
        fits=fits,
    )


def _identity(data: SearchInput, declined) -> DecisionIdentity:
    i = data.identity
    return DecisionIdentity(
        project_id=i.project_id,
        inventory_revision_id=i.inventory_revision_id,
        active_version_id=i.active_version_id,
        last_event_id=i.last_event_id,
        context_fingerprint=i.context_fingerprint,
        measurement_record_ids=i.measurement_record_ids,
        declined_target_keys=tuple(sorted(declined)),
    )


def _finish(identity: DecisionIdentity, **values) -> MeasurementDecision:
    draft = MeasurementDecision(
        decision_id="0" * 64, identity=identity, selection_rule=SELECTION_RULE, **values
    )
    body = draft.model_dump(mode="json", exclude={"decision_id"})
    return draft.model_copy(update={"decision_id": _digest(body)})


def _question(identity, target, **values) -> MeasurementQuestion:
    question_id = _digest(
        {
            "identity": identity.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
        }
    )
    return MeasurementQuestion(question_id=question_id, target=target, **values)


def _facts(data: SearchInput) -> tuple[SavedFact, ...]:
    facts = []
    for stock in sorted(data.stocks, key=lambda s: s.id):
        if stock.kind == "sheet":
            props = SHEET_PROPERTIES
        elif stock.kind == "tape":
            props = TAPE_PROPERTIES
        else:
            continue
        for prop in props:
            measurement = getattr(stock, prop)
            facts.append(
                SavedFact(
                    key=f"stock:{stock.id}:{prop}",
                    value=measurement.value,
                    confirmed=measurement.confirmed,
                )
            )
        if stock.kind == "sheet":
            facts.append(
                SavedFact(
                    key=f"stock:{stock.id}:usable_region",
                    value=float(len(stock.usable_regions)),
                    confirmed=bool(stock.usable_regions),
                )
            )
    if data.constraints is not None:
        for name, _, _ in REQUIREMENTS:
            measurement = getattr(data.constraints, name)
            facts.append(
                SavedFact(
                    key=f"requirement:constraints:{name}",
                    value=measurement.value,
                    confirmed=measurement.confirmed,
                )
            )
    return tuple(facts)


def _design_summary(result: SynthesisResult) -> DesignSummary:
    return DesignSummary(
        search_id=result.search_id,
        status=result.status,
        candidate_ids=tuple(c.candidate_id for c in result.candidates),
        nodes_evaluated=result.nodes_evaluated,
        nodes_total=result.nodes_total,
    )


def _settings_missing(data: SearchInput) -> bool:
    """No server design settings resolved for this exact inventory revision."""
    return (
        data.process is None
        and data.parameters is None
        and not data.joint_profiles
        and bool(data.context_blockers)
    )


def _context_gaps(data: SearchInput) -> list[str]:
    """Server-owned inputs: a user measurement cannot supply them."""
    if _settings_missing(data):
        return [b.message for b in data.context_blockers] + [
            f"Design settings are needed for inventory revision "
            f"{data.identity.inventory_revision_id} before the search can run, and "
            "no earlier revision's settings apply to this stock. Saved measurements "
            "are kept; recalculate once the settings exist."
        ]
    gaps = []
    if data.process is None or not data.process.verified(
        allow_synthetic=data.allow_synthetic
    ):
        gaps.append("A measured, verified cutting process is not configured.")
    if data.parameters is None:
        gaps.append("Confirmed stand parameters are not configured.")
    else:
        for name in (
            "lip_mm",
            "device_width_mm",
            "device_contact_height_mm",
            "device_thickness_mm",
            "tape_overlap_mm",
        ):
            if _confirmed(getattr(data.parameters, name)) is None:
                gaps.append(f"The stand parameter {name} is not confirmed.")
        if not (
            data.parameters.tools_confirmed and data.parameters.joint_access_confirmed
        ):
            gaps.append("Tool and hinge-access confirmations are missing.")
    if data.kerf_mm is None or data.edge_margin_mm is None:
        gaps.append("The selected kerf and edge margin are not configured.")
    if not profile_materials(data):
        gaps.append(
            "No reviewed tape and fold profile pair with thickness limits is configured."
        )
    gaps.extend(b.message for b in data.context_blockers)
    return gaps


def design_decision(
    data: SearchInput,
    result: SynthesisResult,
    declined: frozenset[str] = frozenset(),
    invalidated: tuple[str, ...] = (),
) -> MeasurementDecision:
    """The next useful measurement before a build, or why there is none."""
    identity = _identity(data, declined)
    common = dict(
        facts=_facts(data),
        design=_design_summary(result),
        invalidated=invalidated,
        settings=data.settings_notes,
    )
    candidate_ids = tuple(c.candidate_id for c in result.candidates)
    questions: list[MeasurementQuestion] = []

    if data.constraints is None or any(
        _confirmed(getattr(data.constraints, name)) is None
        for name, _, _ in REQUIREMENTS
    ):
        for name, unit, label in REQUIREMENTS:
            measurement = getattr(data.constraints, name) if data.constraints else None
            key = f"requirement:constraints:{name}"
            if _confirmed(measurement) is not None or key in declined:
                continue
            target = MeasurementTarget(
                key=key, kind="requirement", property=name, label=label
            )
            questions.append(
                _question(
                    identity,
                    target,
                    unit=unit,
                    method="Measure the device or the space it must fit, then confirm it in the build requirements.",
                    where="Build requirements in the inventory step",
                    current=_current(measurement) if measurement else None,
                    precision_basis="The search cannot run until this requirement is confirmed; it bounds every design.",
                    why=f"{label} is unconfirmed, so no design can be searched or checked.",
                    capture="requirements",
                )
            )
        if questions:
            return _finish(
                identity,
                outcome="question",
                question=questions[0],
                pending_questions=len(questions) - 1,
                reasons=("Build requirements bound every design.",),
                **common,
            )
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=("Every missing build requirement was marked unavailable.",),
            **common,
        )

    gaps = _context_gaps(data)
    if gaps:
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=tuple(gaps[:16]),
            missing_capabilities=(
                SETTINGS_GAP
                if _settings_missing(data)
                else "These are server design-context inputs, not measurements the builder can record here.",
            ),
            **common,
        )

    tapes = sorted((s for s in data.stocks if s.kind == "tape"), key=lambda s: s.id)
    sheets = sorted((s for s in data.stocks if s.kind == "sheet"), key=lambda s: s.id)
    materials = sorted({s.material for s in sheets}) or list(profile_materials(data))
    by_material = {material: thresholds(data, material) for material in materials}
    usable = {k: v for k, v in by_material.items() if isinstance(v, Thresholds)}
    blocked = {k: v for k, v in by_material.items() if isinstance(v, Blocked)}
    # Sheets whose material has no threshold are never asked about: no
    # measurement of them can enable the search.
    inapplicable = tuple(
        f"Sheet {s.id} ({s.material}): {blocked[s.material].reasons[0]}"
        for s in sheets
        if s.material in blocked
    )
    if not usable:
        kinds = {b.kind for b in blocked.values()}
        reasons = tuple(dict.fromkeys(r for b in blocked.values() for r in b.reasons))
        if kinds <= {"infeasible"}:
            return _finish(
                identity,
                outcome="no_feasible_candidate",
                pending_questions=0,
                reasons=reasons[:16],
                **common,
            )
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=(inapplicable + reasons)[:16],
            missing_capabilities=(
                "These are server design-context inputs, not measurements the builder can record here.",
            ),
            **common,
        )
    # Tape is usable with any applicable sheet material; use the least demanding.
    reference = min(usable.values(), key=lambda t: (t.tape_length_mm, t.material))

    def describe(limits: Thresholds):
        return (
            f"the smallest searched design ({limits.design.part_width_mm:g} mm panels, "
            f"{limits.design.support_length_mm:g} mm support, "
            f"{limits.design.footprint_depth_mm:g} mm base)"
        )

    def ranges_text(limits: Thresholds):
        return ", ".join(
            f"{low:g}–{high:g} mm" for low, high in limits.thickness_ranges
        )

    def tape_usable(stock):
        width, length = (
            _confirmed(stock.width_mm),
            _confirmed(stock.remaining_length_mm),
        )
        return (
            width is not None
            and length is not None
            and width >= reference.tape_width_mm
            and length >= reference.tape_length_mm
        )

    def tape_excluded(stock):
        width, length = (
            _confirmed(stock.width_mm),
            _confirmed(stock.remaining_length_mm),
        )
        return (width is not None and width < reference.tape_width_mm) or (
            length is not None and length < reference.tape_length_mm
        )

    def sheet_excluded(stock):
        limits = usable[stock.material]
        width, height, thickness = (
            _confirmed(stock.width_mm),
            _confirmed(stock.height_mm),
            _confirmed(stock.thickness_mm),
        )
        regions = stock.usable_regions
        if len(regions) > 1 or (regions and regions[0].geometry.rotation_deg != 0):
            return True
        if thickness is not None and not any(
            low <= thickness <= high for low, high in limits.thickness_ranges
        ):
            return True

        def short(w, h):
            # Below the rounded threshold, the compiler decides exactly.
            return (w < limits.width_mm or h < limits.height_mm) and not limits.fits(
                w, h, thickness
            )

        return (
            (width is not None and short(width, PROBE_MM))
            or (height is not None and short(PROBE_MM, height))
            or bool(
                regions and short(regions[0].geometry.width, regions[0].geometry.height)
            )
        )

    candidates = [s for s in sheets if s.material in usable]

    def declined_stock(stock, props):
        return any(f"stock:{stock.id}:{p}" in declined for p in props)

    tape_questions = []
    if not any(tape_usable(t) for t in tapes):
        for tape in tapes:
            if tape_excluded(tape) or declined_stock(tape, TAPE_PROPERTIES):
                continue
            for prop in TAPE_PROPERTIES:
                measurement = getattr(tape, prop)
                if _confirmed(measurement) is not None:
                    continue
                needed = (
                    reference.tape_width_mm
                    if prop == "width_mm"
                    else reference.tape_length_mm
                )
                basis = (
                    "Each hinge needs the confirmed tape overlap on both faces."
                    if prop == "width_mm"
                    else f"The three hinges of {describe(reference)} use {needed:g} mm of tape, per the compiler."
                )
                tape_questions.append(
                    _question(
                        identity,
                        MeasurementTarget(
                            key=f"stock:{tape.id}:{prop}",
                            kind="stock",
                            property=prop,
                            stock_id=tape.id,
                            label=f"{'Width' if prop == 'width_mm' else 'Remaining length'} of tape {tape.id}",
                        ),
                        unit="mm",
                        method="Lay the tape flat against a ruler; for length, unroll or measure the remaining roll.",
                        where=f"Tape {tape.id}",
                        current=_current(measurement),
                        threshold=DecisionThreshold(
                            comparison="at_least", lower=needed, unit="mm", basis=basis
                        ),
                        required_precision=1.0,
                        precision_basis=f"Only whether it is at least {needed:g} mm changes the decision; a reading to the nearest millimetre settles it unless it lands within 1 mm.",
                        affected_candidate_ids=candidate_ids,
                        why=(
                            f"No saved tape is confirmed usable, so no design can be made. "
                            f"If tape {tape.id} has at least {needed:g} mm, designs become possible; if not, it is excluded."
                        ),
                        capture="inventory",
                    )
                )
    any_tape_possible = any(tape_usable(t) for t in tapes) or bool(tape_questions)

    sheet_questions = []
    for sheet in candidates:
        if sheet_excluded(sheet) or declined_stock(
            sheet, SHEET_PROPERTIES + ("usable_region",)
        ):
            continue
        limits = usable[sheet.material]
        for prop in SHEET_PROPERTIES:
            measurement = getattr(sheet, prop)
            if _confirmed(measurement) is not None:
                continue
            if prop == "thickness_mm":
                threshold = DecisionThreshold(
                    comparison="within",
                    lower=limits.thickness_ranges[0][0],
                    upper=limits.thickness_ranges[0][1],
                    unit="mm",
                    basis=f"Reviewed tape and fold profiles for {sheet.material} accept {ranges_text(limits)}.",
                )
                precision, precision_basis = (
                    None,
                    f"The reading must show whether the thickness lies within {ranges_text(limits)}.",
                )
                rule = f"within {ranges_text(limits)}"
            else:
                needed = limits.width_mm if prop == "width_mm" else limits.height_mm
                threshold = DecisionThreshold(
                    comparison="at_least",
                    lower=needed,
                    unit="mm",
                    basis=f"Smallest sheet {prop[:-3]} that compiles {describe(limits)}, found by the compiler in 0.1 mm steps.",
                )
                precision, precision_basis = (
                    1.0,
                    f"A reading to the nearest millimetre settles it unless it lands within 1 mm of {needed:g} mm; a confirmed value just below is checked against the compiler directly.",
                )
                rule = f"at least {needed:g} mm"
            sheet_questions.append(
                _question(
                    identity,
                    MeasurementTarget(
                        key=f"stock:{sheet.id}:{prop}",
                        kind="stock",
                        property=prop,
                        stock_id=sheet.id,
                        label=f"{prop[:-3].capitalize()} of sheet {sheet.id}",
                    ),
                    unit="mm",
                    method=(
                        "Measure the edge with calipers or a ruler at a clean, uncrushed corner."
                        if prop == "thickness_mm"
                        else "Measure the usable flat sheet edge to edge with a ruler."
                    ),
                    where=f"Sheet {sheet.id}",
                    current=_current(measurement),
                    threshold=threshold,
                    required_precision=precision,
                    precision_basis=precision_basis,
                    affected_candidate_ids=candidate_ids,
                    why=(
                        f"Sheet {sheet.id} is left out of the search until its {prop[:-3]} is confirmed. "
                        f"If it is {rule}, the search can use it"
                        + (
                            " and it could replace a current proposal that uses a larger region"
                            if candidate_ids
                            else ""
                        )
                        + "; otherwise it stays excluded."
                    ),
                    capture="inventory",
                )
            )
        width, height = _confirmed(sheet.width_mm), _confirmed(sheet.height_mm)
        if not sheet.usable_regions and width is not None and height is not None:
            sheet_questions.append(
                _question(
                    identity,
                    MeasurementTarget(
                        key=f"stock:{sheet.id}:usable_region",
                        kind="stock",
                        property="usable_region",
                        stock_id=sheet.id,
                        label=f"Usable area of sheet {sheet.id}",
                    ),
                    unit="mm",
                    method="Check the whole sheet for tears, folds, crushed edges or tape; confirm only if the full measured rectangle is flat and usable.",
                    where=f"Sheet {sheet.id}, all {width:g} × {height:g} mm",
                    current=None,
                    threshold=DecisionThreshold(
                        comparison="at_least",
                        lower=limits.width_mm,
                        unit="mm",
                        basis=f"The cut layout needs one flat rectangle of about {limits.width_mm:g} × {limits.height_mm:g} mm or more.",
                    ),
                    precision_basis="A yes/no inspection: the cut layout needs one undamaged rectangle.",
                    affected_candidate_ids=candidate_ids,
                    why=(
                        f"No usable area is recorded for sheet {sheet.id}, so the cut layout cannot place panels on it. "
                        "Confirming that the whole measured sheet is usable lets the search include it."
                    ),
                    capture="inventory",
                )
            )
    any_sheet_possible = bool(sheet_questions) or any(
        not sheet_excluded(s)
        and all(_confirmed(getattr(s, p)) is not None for p in SHEET_PROPERTIES)
        and s.usable_regions
        for s in candidates
    )
    # A question on one material cannot change anything if the other material
    # is already known to block every design.
    questions = (tape_questions if any_sheet_possible else []) + (
        sheet_questions if any_tape_possible else []
    )
    if questions:
        return _finish(
            identity,
            outcome="question",
            question=questions[0],
            pending_questions=len(questions) - 1,
            reasons=(
                f"{len(questions)} saved stock value(s) can change which designs fit.",
            )
            + inapplicable[:15],
            **common,
        )
    excluded = (
        tuple(
            f"Stock {s.id} is confirmed outside the compiler thresholds."
            for s in candidates
            if sheet_excluded(s)
        )
        + tuple(
            f"Tape {t.id} is confirmed too narrow or too short."
            for t in tapes
            if tape_excluded(t)
        )
        + inapplicable
    )
    if result.status == "candidates_found":
        return _finish(
            identity,
            outcome="physical_test_required",
            pending_questions=0,
            reasons=(
                "Every saved value that can change which designs fit is confirmed.",
                "Stability, retention and strength need a built stand: approve a design, build it, then record its measurements.",
            ),
            missing_capabilities=(STABILITY_GAP, RETENTION_GAP),
            **common,
        )
    if result.status == "search_exhausted":
        return _finish(
            identity,
            outcome="budget_exhausted",
            pending_questions=0,
            reasons=(
                "The design search ran out of budget before finding a design; no measurement is selected from a partial search.",
            ),
            **common,
        )
    if data.uncovered_stock_ids and not (any_sheet_possible and any_tape_possible):
        # Saved stock exists but the settings in use do not cover it; that is
        # the operator's review, not proof that no design can fit.
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=(
                tuple(data.settings_notes[1:])
                or ("Some saved stock is not covered by the design settings in use.",)
            )[:16],
            missing_capabilities=(
                "Settings that cover the named stock need the operator's review; a measurement cannot supply them.",
            ),
            **common,
        )
    if result.status == "infeasible" or not (any_sheet_possible and any_tape_possible):
        if blocked and not any_sheet_possible and any_tape_possible:
            # The only sheets that could help are of a material the server
            # has no reviewed profiles or inputs for.
            if any(b.kind != "infeasible" for b in blocked.values()) and any(
                s.material in blocked for s in sheets
            ):
                return _finish(
                    identity,
                    outcome="unsupported",
                    pending_questions=0,
                    reasons=excluded[:16],
                    missing_capabilities=(
                        "These are server design-context inputs, not measurements the builder can record here.",
                    ),
                    **common,
                )
        return _finish(
            identity,
            outcome="no_feasible_candidate",
            pending_questions=0,
            reasons=(
                f"Designs need a flat {reference.material} sheet of about {usable[reference.material].width_mm:g} × "
                f"{usable[reference.material].height_mm:g} mm or more with thickness {ranges_text(reference)}, "
                f"and tape at least {reference.tape_width_mm:g} mm wide with {reference.tape_length_mm:g} mm remaining.",
            )
            + excluded[:15],
            **common,
        )
    return _finish(
        identity,
        outcome="unsupported",
        pending_questions=0,
        reasons=tuple(b.message for b in result.blockers[:16])
        or ("The search needs inputs that a measurement here cannot supply.",),
        **common,
    )


@dataclass(frozen=True)
class CaseMargin:
    case_id: str
    status: str
    signed_margin_m: float | None


@dataclass(frozen=True)
class ActiveFacts:
    """Facts from the authorized #146/#147 analysis of the active plan."""

    data: SearchInput
    plan_version_id: str
    analysis_status: Literal[
        "complete", "needs_geometry", "needs_measurement", "unsupported"
    ]
    stage: str | None
    part_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    cases: tuple[CaseMargin, ...] = ()
    required_margin_m: float | None = None
    resolution_band_m: float | None = None


def active_decision(
    facts: ActiveFacts, declined: frozenset[str] = frozenset()
) -> MeasurementDecision:
    """The next measurement of the built stand, or why there is none."""
    identity = _identity(facts.data, declined)
    summary = StabilitySummary(
        plan_version_id=facts.plan_version_id,
        analysis_status=facts.analysis_status,
        case_margins_m=tuple((c.case_id, c.signed_margin_m) for c in facts.cases),
        required_margin_m=facts.required_margin_m,
    )
    common = dict(
        facts=_facts(facts.data), stability=summary, settings=facts.data.settings_notes
    )
    key = f"assembled_stand:{facts.plan_version_id}:assembled_stand"
    if facts.analysis_status in ("unsupported", "needs_geometry"):
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=tuple(facts.blockers[:16])
            or ("This build state has no supported stability geometry.",),
            missing_capabilities=(
                "Stage, damaged or repaired geometry needs a supported continuation of the shared geometry producer.",
            ),
            **common,
        )
    if facts.analysis_status == "needs_measurement":
        if facts.stage != "reported_assembled":
            return _finish(
                identity,
                outcome="physical_test_required",
                pending_questions=0,
                reasons=(
                    "Assembled-stand measurements need the built stand. Record the build steps first; nothing can be measured on an unbuilt plan.",
                ),
                missing_capabilities=(STABILITY_GAP,),
                **common,
            )
        if key in declined:
            return _finish(
                identity,
                outcome="physical_test_required",
                pending_questions=0,
                reasons=(
                    "The assembled-stand measurement was marked unavailable; the remaining check is the defined physical function test.",
                ),
                missing_capabilities=(STABILITY_GAP,),
                **common,
            )
        pieces = tuple(
            PieceReference(
                part_id=part,
                reference=piece_reference(part),
                display_name=PIECES.get(part, part),
                geometry_class="rectangle",
            )
            for part in sorted(facts.part_ids)
            if part in PIECES
        )
        question = _question(
            identity,
            MeasurementTarget(
                key=key,
                kind="assembled_stand",
                property="assembled_stand",
                label="Assembled stand and device: mass, centre of mass and support contact",
                pieces=pieces,
            ),
            unit="batch",
            method="Weigh the assembled stand with all panels and tape together; locate its centre of mass by balancing; record the device mass, centre of mass and pose for portrait and landscape, and the actual support rectangle.",
            where="The built stand on the surface you will use",
            precision_basis="The form records each instrument's resolution with the value; the point-estimate report does not propagate it into a bound.",
            affected_case_ids=("portrait", "landscape"),
            why="Tipping in portrait and landscape cannot be computed without these values; with them the engine reports a modeled margin for each case.",
            capture="stability_measurements",
        )
        return _finish(
            identity,
            outcome="question",
            question=question,
            pending_questions=0,
            reasons=(
                "The stand is reported assembled and has no current measurements.",
            ),
            **common,
        )
    reasons = []
    unresolved = False
    for case in facts.cases:
        if case.signed_margin_m is None or facts.required_margin_m is None:
            unresolved = True
            reasons.append(f"{case.case_id}: no computed margin ({case.status}).")
            continue
        distance = case.signed_margin_m - facts.required_margin_m
        side = "above" if distance > 0 else "below"
        within = (
            facts.resolution_band_m is not None
            and abs(distance) <= facts.resolution_band_m
        )
        unresolved |= within
        reasons.append(
            f"{case.case_id}: modeled margin {case.signed_margin_m * 1000:.1f} mm is "
            f"{abs(distance) * 1000:.1f} mm {side} the required {facts.required_margin_m * 1000:.1f} mm"
            + (
                f", inside the recorded resolution of {facts.resolution_band_m * 1000:.1f} mm."
                if within
                else "."
            )
        )
    if unresolved:
        return _finish(
            identity,
            outcome="unsupported",
            pending_questions=0,
            reasons=tuple(reasons[:16]),
            missing_capabilities=(
                "Conservative interval propagation of measurement resolution is not implemented; repeating the measurement with the same instruments cannot settle a margin inside its resolution. A physical tip test is the remaining check.",
            ),
            **common,
        )
    return _finish(
        identity,
        outcome="none_needed",
        pending_questions=0,
        reasons=tuple(reasons[:15])
        + (
            "Point estimates only: the result is modeled, not a physical pass; the defined function test is still required.",
        ),
        **common,
    )


def compare(before: MeasurementDecision, after: MeasurementDecision) -> DecisionChange:
    """What changed between two decisions and whether the decision changed."""
    old = {f.key: f for f in before.facts}
    new = {f.key: f for f in after.facts}
    changed = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a != b:

            def show(f):
                if f is None:
                    return "absent"
                if f.value is None:
                    return "unknown"
                return f"{f.value:g}" + ("" if f.confirmed else " (unconfirmed)")

            changed.append(f"{key}: {show(a)} → {show(b)}")
    for key in sorted(
        set(after.identity.declined_target_keys)
        - set(before.identity.declined_target_keys)
    ):
        changed.append(f"{key}: marked unavailable")
    records = (
        len(before.identity.measurement_record_ids),
        len(after.identity.measurement_record_ids),
    )
    if before.identity.measurement_record_ids != after.identity.measurement_record_ids:
        changed.append(
            f"assembled-stand measurement records: {records[0]} → {records[1]}"
        )
    asked = (
        before.question.target.key if before.question else None,
        after.question.target.key if after.question else None,
    )

    def decision_of(d: MeasurementDecision):
        return (
            d.outcome,
            d.design.status if d.design else None,
            d.design.candidate_ids if d.design else None,
            d.stability.analysis_status if d.stability else None,
            d.stability.case_margins_m if d.stability else None,
        )

    differs = decision_of(before) != decision_of(after)
    if differs:
        parts = [f"outcome {before.outcome} → {after.outcome}"]
        if before.design and after.design:
            parts.append(
                f"design search {before.design.status} ({len(before.design.candidate_ids)} proposal(s)) → "
                f"{after.design.status} ({len(after.design.candidate_ids)} proposal(s))"
            )
        if before.stability and after.stability:
            parts.append(
                f"stability {before.stability.analysis_status} → {after.stability.analysis_status}"
            )
        explanation = "The decision changed: " + "; ".join(parts) + "."
    elif changed:
        explanation = (
            "The saved values changed, but no supported decision changed: "
            + (after.reasons[0] if after.reasons else after.outcome)
        )
        if asked[0] != asked[1] and after.question:
            explanation += (
                f" The next measurement is now: {after.question.target.label}."
            )
    else:
        explanation = (
            "Nothing the decision depends on has changed since the earlier result."
        )
    return DecisionChange(
        before_decision_id=before.decision_id,
        after_decision_id=after.decision_id,
        changed_facts=tuple(changed),
        decision_changed=differs,
        explanation=explanation,
        after=after,
    )
