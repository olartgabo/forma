"""A narrow triangular tape/fold stand template. No physical success inference."""

from math import cos, hypot, radians, sin

from forma_compiler import CutProcess, validate_plan
from pydantic import Field, ValidationError

from forma_domain import models as m


class StandParameters(m.Record):
    """User-supplied dimensions and physical checks; no assumed safe defaults."""

    footprint_depth_mm: m.Measurement
    lip_mm: m.Measurement
    device_width_mm: m.Measurement
    device_thickness_mm: m.Measurement
    device_contact_height_mm: m.Measurement
    tape_overlap_mm: m.Measurement
    tools_confirmed: bool
    joint_access_confirmed: bool
    device_label: m.Text
    test_duration_seconds: m.Positive
    test_surface: m.Text
    test_pass_criteria: tuple[m.Text, ...] = Field(min_length=1)
    profile_evidence: tuple[m.Evidence, ...]


def blocked(code, message, *ids):
    return m.CompilerResult(
        status="needs_measurement" if code == "missing_measurement" else "blocked",
        plan=None,
        blockers=(m.Blocker(code=code, message=message, target_ids=ids),),
    )


def profile_evidence_valid(profiles, evidence, project_id, *, allow_synthetic):
    items = {e.id: e for e in evidence}
    if len(items) != len(evidence):
        return False
    return all(
        profile.status == "tested"
        and bool(profile.test_evidence_ids)
        and all(
            eid in items
            and items[eid].project_id == project_id
            and (
                (
                    items[eid].kind == "physical_test"
                    and items[eid].provenance == "user"
                    and items[eid].verification_state == "user_confirmed"
                )
                or (
                    allow_synthetic
                    and items[eid].provenance == "synthetic_fixture"
                    and items[eid].verification_state == "unknown"
                )
            )
            for eid in profile.test_evidence_ids
        )
        for profile in profiles
    )


def _compile_stand(
    request: m.CompilerInput,
    parameters: StandParameters,
    *,
    process: CutProcess | None = None,
    allow_synthetic: bool = False,
) -> m.CompilerResult:
    """Compile one three-panel tape stand, then apply the independent validator.

    Flat cut coordinates remain in the stock frame. The support length excludes
    its folded retaining lip. Base/front, base/rear and apex use tape hinges.
    Geometry is a zero-thickness nominal layout; actual thickness/fold allowance,
    grip, device contact and load performance require the supplied tested profiles
    and the mandatory manual checks, never an inferred safety rating.
    """
    candidate, limits = request.candidate, request.constraints
    if candidate.panel_count != 3:
        return blocked("unsupported", "This template requires exactly three panels.")
    for name in (
        "footprint_depth_mm",
        "lip_mm",
        "device_width_mm",
        "device_thickness_mm",
        "device_contact_height_mm",
        "tape_overlap_mm",
    ):
        value = getattr(parameters, name)
        if (
            value.unit != "mm"
            or value.value is None
            or not value.confirmed
            or value.value <= 0
        ):
            return blocked("missing_measurement", f"Confirm positive mm for {name}.")
    for name in (
        "device_mass_g",
        "support_angle_deg",
        "max_footprint_width_mm",
        "max_footprint_height_mm",
    ):
        value = getattr(limits, name)
        if value.value is None or not value.confirmed or value.value <= 0:
            return blocked("missing_measurement", f"Confirm {name}.")
    if not parameters.tools_confirmed or not parameters.joint_access_confirmed:
        return blocked(
            "needs_confirmation",
            "Confirm suitable tools and access to all three tape hinges.",
        )
    if process is None or not process.verified(allow_synthetic=allow_synthetic):
        return blocked(
            "unsupported_profile", "Supply verified cutting process evidence."
        )
    if any(e.project_id != request.project_id for e in process.evidence):
        return blocked(
            "invalid_reference", "Cut process evidence belongs to another project."
        )
    if set(request.process_evidence_ids) != {e.id for e in process.evidence}:
        return blocked(
            "invalid_reference", "Request process evidence must match measured process."
        )
    chosen_profiles = [
        p for p in request.joint_profiles if p.id in candidate.profile_ids
    ]
    if (
        len(chosen_profiles) != 2
        or len(set(candidate.profile_ids)) != 2
        or len({p.id for p in request.joint_profiles}) != len(request.joint_profiles)
    ):
        return blocked(
            "invalid_reference", "Select exactly two unique existing profile IDs."
        )
    profiles = {
        p.strategy: p for p in request.joint_profiles if p.id in candidate.profile_ids
    }
    if set(profiles) != {"tape", "fold_brace"}:
        return blocked(
            "unsupported_profile", "Select one measured tape and one fold profile."
        )
    if not profile_evidence_valid(
        profiles.values(),
        parameters.profile_evidence,
        request.project_id,
        allow_synthetic=allow_synthetic,
    ):
        return blocked(
            "unsupported_profile",
            "Profile needs user-observed physical evidence; fixtures require opt-in.",
        )
    stocks = {s.id: s for s in request.stocks}
    if len(stocks) != len(request.stocks) or len(set(candidate.stock_ids)) != len(
        candidate.stock_ids
    ):
        return blocked("invalid_reference", "Stock IDs must be unique.")
    if not set(candidate.stock_ids) <= stocks.keys():
        return blocked("invalid_reference", "Candidate references missing stock.")
    selected = [stocks[sid] for sid in candidate.stock_ids]
    sheets = [s for s in selected if s.kind == "sheet"]
    tapes = [s for s in selected if s.kind == "tape"]
    if (
        len(sheets) != 1
        or len(tapes) != 1
        or len(selected) != 2
        or len(sheets[0].usable_regions) != 1
    ):
        return blocked(
            "unsupported",
            "Template requires one sheet with one usable region and one tape stock.",
        )
    sheet, tape = sheets[0], tapes[0]
    if tape.width_mm.value is None or not tape.width_mm.confirmed:
        return blocked(
            "missing_measurement",
            "Confirm tape width for the required overlap.",
            tape.id,
        )
    if tape.width_mm.value < 2 * parameters.tape_overlap_mm.value:
        return blocked(
            "geometry_invalid",
            "Tape width cannot provide the required overlap on both faces.",
            tape.id,
        )
    for profile in profiles.values():
        thickness = sheet.thickness_mm
        if thickness.value is None or not thickness.confirmed:
            return blocked("missing_measurement", "Confirm sheet thickness.", sheet.id)
        if (
            profile.material != sheet.material
            or profile.thickness_min_mm is None
            or profile.thickness_max_mm is None
            or not profile.thickness_min_mm
            <= thickness.value
            <= profile.thickness_max_mm
        ):
            return blocked(
                "unsupported_profile",
                "Sheet is outside measured fold/tape material limits.",
                profile.id,
            )
    width, blank = candidate.part_width_mm, candidate.part_height_mm
    lip = parameters.lip_mm.value
    support = blank - lip
    depth = parameters.footprint_depth_mm.value
    theta = radians(candidate.support_angle_deg)
    reach, rise = support * cos(theta), support * sin(theta)
    brace = hypot(depth - reach, rise)
    if (
        support <= 0
        or depth <= reach
        or abs(candidate.support_angle_deg - limits.support_angle_deg.value) > 1e-7
    ):
        return blocked(
            "geometry_invalid",
            "Lip, angle and rear base contact must form a nondegenerate triangle.",
        )
    if (
        width > limits.max_footprint_width_mm.value
        or depth > limits.max_footprint_height_mm.value
    ):
        return blocked("geometry_invalid", "Stand exceeds confirmed footprint limits.")
    if (
        parameters.device_width_mm.value > width
        or parameters.device_contact_height_mm.value > support
        or parameters.device_thickness_mm.value > lip
    ):
        return blocked(
            "geometry_invalid",
            "Confirmed device contact dimensions exceed support or retaining lip.",
        )
    if parameters.tape_overlap_mm.value * 2 >= min(support, depth, brace):
        return blocked(
            "geometry_invalid", "Tape overlap exceeds available hinge contact surfaces."
        )
    region = sheet.usable_regions[0]
    margin, kerf = request.edge_margin_mm, request.kerf_mm
    y = region.geometry.y + margin
    parts = []
    for name, height in (("support", blank), ("base", depth), ("brace", brace)):
        features = ()
        if name == "support":
            features = (
                m.Feature(
                    id="stand-lip-fold",
                    kind="fold",
                    geometry=m.Rect(x=0, y=support, width=width, height=lip),
                ),
            )
        parts.append(
            m.Part(
                id=f"stand-{name}",
                source_stock_id=sheet.id,
                source_region_id=region.id,
                geometry=m.Rect(
                    x=region.geometry.x + margin, y=y, width=width, height=height
                ),
                features=features,
                condition="usable",
            )
        )
        y += height + kerf
    joints = tuple(
        m.Joint(
            id=f"stand-joint-{name}",
            profile_id=profiles["tape"].id,
            part_ids=pids,
            confirmed_accessible=True,
        )
        for name, pids in (
            ("front", ("stand-support", "stand-base")),
            ("rear", ("stand-base", "stand-brace")),
            ("apex", ("stand-support", "stand-brace")),
        )
    )
    pre = m.Preconditions(
        safe_tools_confirmed=True,
        human_checks=(
            "Confirm stock measurements, tested profiles, cutting process and safe tool handling before cutting.",
        ),
    )
    operations = [
        m.CutRect(
            id="stand-cut-panels",
            type="cut_rect",
            part_ids=(),
            stock_ids=(sheet.id,),
            expected_state_id="stand-state-cut",
            preconditions=pre,
            effects=m.Effects(
                created_part_ids=tuple(p.id for p in parts),
                consumed_region_ids=(region.id,),
            ),
            args=m.CutRectArgs(
                stock_id=sheet.id,
                source_region_id=region.id,
                child_part_ids=tuple(p.id for p in parts),
                kerf_mm=kerf,
                edge_margin_mm=margin,
            ),
        )
    ]
    checkpoints = []

    def inspect(id, target_ids, description, dependency):
        checkpoint = f"{id}-check"
        operations.append(
            m.Inspect(
                id=id,
                type="inspect",
                part_ids=target_ids,
                depends_on=(dependency,),
                expected_state_id=f"{id}-state",
                preconditions=m.Preconditions(),
                effects=m.Effects(),
                args=m.InspectArgs(
                    target_ids=target_ids, checkpoint_id=checkpoint, method="ruler"
                ),
            )
        )
        checkpoints.append(
            m.Checkpoint(
                id=checkpoint,
                after_operation_id=id,
                method="ruler",
                description=description,
            )
        )

    inspect(
        "stand-inspect-cuts",
        tuple(p.id for p in parts),
        "Measure all three panels against the cut dimensions; reject torn or inaccurate cuts.",
        operations[-1].id,
    )
    operations.append(
        m.Fold(
            id="stand-fold-lip",
            type="fold",
            part_ids=("stand-support",),
            depends_on=(operations[-1].id,),
            expected_state_id="stand-state-folded",
            preconditions=m.Preconditions(
                accessible_part_ids=("stand-support",),
                human_checks=(
                    "Check real fold allowance and cracking against the measured profile.",
                ),
            ),
            effects=m.Effects(changed_part_ids=("stand-support",)),
            args=m.FoldArgs(
                part_id="stand-support",
                feature_id="stand-lip-fold",
                start_x_mm=0,
                start_y_mm=support,
                end_x_mm=width,
                end_y_mm=support,
                angle_deg=90,
                direction="valley",
                reachable_face="front",
            ),
        )
    )
    for joint in joints:
        operations.append(
            m.TapeJoint(
                id=f"{joint.id}-attach",
                type="tape_joint",
                part_ids=joint.part_ids,
                stock_ids=(tape.id,),
                depends_on=(operations[-1].id,),
                expected_state_id=f"{joint.id}-state",
                reversible="lossy",
                preconditions=m.Preconditions(
                    accessible_part_ids=joint.part_ids,
                    human_checks=(
                        f"Hold the specified triangle angle; verify {parameters.tape_overlap_mm.value} mm overlap on each face, access and actual grip by hand.",
                    ),
                ),
                effects=m.Effects(attached_joint_ids=(joint.id,)),
                args=m.ConsumableJointArgs(
                    joint_id=joint.id, stock_id=tape.id, length_mm=width
                ),
            )
        )
    inspect(
        "stand-inspect-fit",
        tuple(p.id for p in parts),
        "Check all hinges, retaining lip, measured angle and flat base contact manually before adding the device.",
        operations[-1].id,
    )
    test_id = "stand-functional-test"
    operations.append(
        m.FunctionalTest(
            id=test_id,
            type="functional_test",
            part_ids=tuple(p.id for p in parts),
            depends_on=(operations[-1].id,),
            expected_state_id="stand-state-tested",
            preconditions=m.Preconditions(
                required_joint_ids=tuple(j.id for j in joints),
                human_checks=(
                    "Stop if unstable, torn or slipping; record the actual result without assuming a pass.",
                ),
            ),
            effects=m.Effects(),
            args=m.FunctionalTestArgs(
                checkpoint_id="stand-function-check",
                procedure="Place the named device, observe stability and retention, then perform the specified user checks.",
                device_label=parameters.device_label,
                mass_g=limits.device_mass_g.value,
                duration_seconds=parameters.test_duration_seconds,
                surface=parameters.test_surface,
                pass_criteria=parameters.test_pass_criteria,
            ),
        )
    )
    checkpoints.append(
        m.Checkpoint(
            id="stand-function-check",
            after_operation_id=test_id,
            method="functional_test",
            description="Record a user-observed pass/fail for the named device and conditions; photograph the final outcome.",
        )
    )
    plan = m.BuildPlan(
        project_id=request.project_id,
        version_id=request.version_id,
        status="draft",
        stocks=request.stocks,
        parts=tuple(parts),
        joint_profiles=request.joint_profiles,
        joints=joints,
        operations=tuple(operations),
        checkpoints=tuple(checkpoints),
        constraints=limits,
        compiler_version="triangular-tape-stand-v1",
        created_at=request.created_at,
    )
    return validate_plan(plan, process=process, allow_synthetic=allow_synthetic)


def compile_stand(
    request: m.CompilerInput,
    parameters: StandParameters,
    *,
    process: CutProcess | None = None,
    allow_synthetic: bool = False,
) -> m.CompilerResult:
    """Return typed blockers for incompatible candidate references and geometry."""
    try:
        return _compile_stand(
            request, parameters, process=process, allow_synthetic=allow_synthetic
        )
    except ValidationError as error:
        return blocked(
            "invalid_reference",
            "Candidate cannot form a valid stand plan: " + str(error)[:1400],
        )
