"""Diagnostic adapter for existing compiled plans; no new geometry/stage rules."""

import hashlib
import json
from datetime import timedelta
from typing import Annotated

from forma_renderer.svg import instruction, tools_for
from pydantic import BaseModel, ConfigDict, Field

from forma_domain.models import BuildPlan, PhysicalEvent
from forma_domain.stability_contracts import (
    AnalysisPolicy,
    BeamDeflection,
    JointDemand,
    SlidingDemand,
    StabilityInput,
)
from forma_domain.stage_mechanics import StageSnapshot
from forma_stability import evaluate_stability
from forma_stability.geometry import UnsupportedGeometry, project_nominal_geometry
from forma_stability.stage import evaluate_stage, flat_parts_example, transform_point

Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class CaseChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sliding: SlidingDemand | None = None
    joint_demands: tuple[JointDemand, ...] = Field(default=(), max_length=32)
    deformation: BeamDeflection | None = None


class PlanLoads(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_mass_g: dict[str, Positive | None]
    device_mass_g: Positive | None
    device_x_mm: Finite | None
    device_y_mm: Finite | None
    device_z_mm: Finite | None
    required_margin_mm: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    tolerance_mm: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    gravity_m_s2: Positive
    uniform_mass_assumed: bool
    connector_shares_included: bool
    full_base_contact_assumed: bool
    rigid_device_attachment_assumed: bool
    case_checks: CaseChecks | None = None


class PlanExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: BuildPlan
    completed_prefix: Annotated[int, Field(strict=True, ge=0, le=64)]
    loads: PlanLoads | None = None
    stage_snapshot: StageSnapshot | None = None
    stage_example: bool = False
    stage_policy: AnalysisPolicy | None = None


def _quantity(value, unit, provenance="assumed"):
    return dict(
        kind="unknown" if value is None else "scalar",
        value=value,
        unit=unit,
        provenance="unknown" if value is None else provenance,
        confirmed=False,
    )


def _packet(plan, geometry, loads):
    if set(loads.part_mass_g) != set(geometry.active_part_ids):
        raise ValueError("Supply exactly one mass for each canonical source part")
    if loads.case_checks and loads.case_checks.joint_demands:
        if {j.joint_id for j in loads.case_checks.joint_demands} != set(
            geometry.attached_joint_ids
        ):
            raise ValueError(
                "Joint checks must cover exactly the assembled stage's active joints"
            )
    centers = {item.part_id: item.centroid for item in geometry.part_centroids}
    bodies = []
    for part_id in geometry.active_part_ids:
        mass = loads.part_mass_g[part_id]
        bodies.append(
            dict(
                body_id=part_id,
                source_part_ids=[part_id],
                mass=_quantity(
                    mass / 1000
                    if mass is not None and loads.connector_shares_included
                    else None,
                    "kg",
                ),
                center_of_mass={
                    axis: _quantity(
                        getattr(centers[part_id], axis)
                        if loads.uniform_mass_assumed
                        else None,
                        "m",
                        "derived",
                    )
                    for axis in ("x", "y", "z")
                },
            )
        )
    bodies.append(
        dict(
            body_id="lab-device",
            body_kind="device",
            source_part_ids=[],
            mass=_quantity(
                loads.device_mass_g / 1000 if loads.device_mass_g is not None else None,
                "kg",
            ),
            center_of_mass={
                axis: _quantity(
                    getattr(loads, f"device_{axis}_mm") / 1000
                    if getattr(loads, f"device_{axis}_mm") is not None
                    else None,
                    "m",
                )
                for axis in ("x", "y", "z")
            },
        )
    )
    contacts = (
        [
            dict(
                contact_id="assumed-base-contact",
                body_id=geometry.ground_part_id,
                active=True,
                polygon_world=[p.model_dump() for p in geometry.ground_polygon],
                assumption_ids=["hypothetical-full-base-contact"],
            )
        ]
        if loads.full_base_contact_assumed
        else []
    )
    analysis = StabilityInput.model_validate(
        dict(
            identity=dict(
                project_id=plan.project_id,
                plan_version_id=plan.version_id,
                inventory_revision="lab-not-inventory",
                history_cursor=geometry.history_cursor,
                operation_state_id="lab-hypothetical-assembly",
                canonical_geometry_hash=geometry.geometry_hash,
                evidence_hash=hashlib.sha256(b"no-evidence").hexdigest(),
                profile_hash=hashlib.sha256(
                    json.dumps(
                        [p.model_dump(mode="json") for p in plan.joint_profiles],
                        sort_keys=True,
                    ).encode()
                ).hexdigest(),
            ),
            geometry_version=geometry.producer_version,
            profile_version="lab-hypothetical-loads-v1",
            mechanical_snapshot=dict(
                bodies=bodies,
                contacts=contacts,
                rigid_assembly=loads.rigid_device_attachment_assumed,
                horizontal_support=True,
                gravity_only=True,
                state_basis="nominal",
                assumption_ids=[
                    "hypothetical-loads-not-measurements",
                    "horizontal-gravity-only",
                ]
                + (
                    ["uniform-sheet-and-allocated-connector-distribution"]
                    if loads.uniform_mass_assumed
                    else []
                )
                + (
                    ["all-connector-shares-included"]
                    if loads.connector_shares_included
                    else []
                )
                + (
                    ["fixed-device-pose-not-verified"]
                    if loads.rigid_device_attachment_assumed
                    else []
                ),
            ),
            cases=[
                dict(
                    case_id="compiled-stand-lab",
                    orientation="Hypothetical fixed device world pose",
                    body_ids=[b["body_id"] for b in bodies],
                    contact_ids=[c["contact_id"] for c in contacts],
                    gravity_m_s2=_quantity(loads.gravity_m_s2, "m_s2"),
                    **(
                        loads.case_checks.model_dump(mode="python")
                        if loads.case_checks
                        else {}
                    ),
                )
            ],
        )
    )
    policy = AnalysisPolicy(
        policy_id="lab-explicit-policy",
        version="v1",
        length_tolerance_m=loads.tolerance_mm / 1000,
        force_tolerance_n=0.0,
        moment_tolerance_n_m=0.0,
        relative_tolerance=0.0,
        required_margin_m=loads.required_margin_mm / 1000,
        uncertainty_method="analytic_interval",
        evaluation_budget=16,
        required_check_types=("support", "tip")
        + (("slide", "joint", "deformation") if loads.case_checks else ()),
        required_case_ids=("compiled-stand-lab",),
    )
    return analysis, policy


def inspect_plan(payload):
    request = PlanExperiment.model_validate(payload)
    plan, prefix = request.plan, request.completed_prefix
    if prefix > len(plan.operations):
        raise ValueError("Selected prefix exceeds the plan's operation count")
    reference = project_nominal_geometry(plan)
    if request.stage_example:
        if request.stage_snapshot is not None:
            raise ValueError("Choose the example or an explicit snapshot, not both")
        request = request.model_copy(
            update=dict(
                stage_snapshot=flat_parts_example(plan, prefix), stage_example=False
            )
        )
    stage_result = None
    stage_overlays = []
    if request.stage_snapshot is not None:
        if request.stage_snapshot.basis != "hypothetical":
            raise ValueError("The lab accepts hypothetical stage inputs only")
        expected = tuple(
            o.id for o in plan.operations[:prefix] if o.type != "functional_test"
        )
        if request.stage_snapshot.completed_operation_ids != expected:
            raise ValueError(
                "Stage snapshot completion must match the selected diagnostic prefix"
            )
        policy = request.stage_policy or AnalysisPolicy(
            policy_id="stage-lab-policy",
            version="v1",
            length_tolerance_m=1e-9,
            force_tolerance_n=1e-9,
            moment_tolerance_n_m=1e-9,
            relative_tolerance=1e-12,
            required_margin_m=0.0,
            uncertainty_method="analytic_interval",
            evaluation_budget=16,
            required_check_types=("support", "tip"),
            required_case_ids=("component-1",),
        )
        stage_result = evaluate_stage(plan, request.stage_snapshot, policy)
        for component in stage_result.reports:
            for overlay in component.overlays:
                stage_overlays.append(
                    overlay.model_copy(
                        update=dict(
                            center_of_mass=transform_point(
                                request.stage_snapshot.support_frame,
                                overlay.center_of_mass,
                            ),
                            support_polygon=tuple(
                                transform_point(request.stage_snapshot.support_frame, p)
                                for p in overlay.support_polygon
                            ),
                            critical_edge=tuple(
                                transform_point(request.stage_snapshot.support_frame, p)
                                for p in overlay.critical_edge
                            ),
                        )
                    ).model_dump(mode="json")
                )
    # In-memory diagnostic replay only. These records are never persisted or
    # represented as actual user work. Functional tests are never marked passed.
    events = tuple(
        PhysicalEvent(
            id=f"lab-hypothetical-{index}",
            project_id=plan.project_id,
            version_id=plan.version_id,
            operation_id=op.id,
            kind="operation_confirmed",
            recorded_at=plan.created_at + timedelta(seconds=index),
            actor="user",
            observation="SYNTHETIC diagnostic prefix only; no physical work performed",
            verification_state="user_confirmed",
        )
        for index, op in enumerate(plan.operations[:prefix])
        if op.type != "functional_test"
    )
    blockers = []
    geometry = None
    analysis = policy = report = None
    try:
        geometry = project_nominal_geometry(plan, history_events=events)
    except UnsupportedGeometry as error:
        blockers.append(str(error))
    if prefix == 0:
        blockers.append(
            "Planned finished shape is reference only. No selected-stage stability is calculated before hypothetical assembly."
        )
    elif geometry is not None and request.loads is not None:
        analysis, policy = _packet(plan, geometry, request.loads)
        report = evaluate_stability(analysis, policy)
    elif geometry is not None:
        blockers.append(
            "Provide explicit hypothetical loads and assumptions to calculate this assembled diagnostic case."
        )
    return dict(
        label="HYPOTHETICAL COMPILED-PLAN INSPECTION - no physical work, evidence or test result is saved",
        request=request.model_dump(mode="json", exclude_unset=True),
        reference_geometry=reference.model_dump(mode="json"),
        selected_geometry=geometry.model_dump(mode="json")
        if geometry is not None
        else None,
        selected_prefix=prefix,
        selected_stage_label="Planned target reference"
        if prefix == 0
        else f"Hypothetical completion of first {prefix} operations; not actual work",
        blockers=blockers,
        operations=[
            dict(
                index=i + 1,
                id=op.id,
                type=op.type,
                instruction=instruction(op, plan),
                tools=list(tools_for(op)),
                depends_on=list(op.depends_on),
                attached_joint_ids=list(op.effects.attached_joint_ids),
                detached_joint_ids=list(op.effects.detached_joint_ids),
                selected_in_prefix=i < prefix,
                physical_test_simulated=False,
            )
            for i, op in enumerate(plan.operations)
        ],
        input=analysis.model_dump(mode="json") if analysis else None,
        policy=policy.model_dump(mode="json") if policy else None,
        report=report.model_dump(mode="json") if report else None,
        stage_analysis=stage_result.model_dump(mode="json") if stage_result else None,
        stage_analysis_world_overlays=stage_overlays,
    )
