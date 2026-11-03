"""Explicit synthetic rectangular-panel proposal through the real fabrication engine.

This adapter never infers inventory or measured process data. Its fixed demo
resources and synthetic evidence are opt-in, not production fabrication approval.
"""

import hashlib
import json
import math
from datetime import UTC, datetime

from forma_compiler import CutProcess
from forma_fabrication import fabrication_report

from forma_domain import models as m
from forma_domain.construction_plan import (
    ConstructionOperationBinding,
    ConstructionPlan,
)
from forma_domain.fabrication_contracts import FabricationInput, VersionHistory

NOW = datetime(2026, 11, 3, tzinfo=UTC)
LABEL = (
    "SYNTHETIC diagnostic resources and process only; not measured or physically tested"
)


def _length(a, b):
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def _rectangle(facet):
    points = facet.vertices_local
    if len(points) != 4:
        return None
    edges = [
        tuple(
            getattr(points[(i + 1) % 4], k) - getattr(points[i], k)
            for k in ("x", "y", "z")
        )
        for i in range(4)
    ]
    lengths = [math.sqrt(sum(v * v for v in edge)) for edge in edges]
    if any(not math.isfinite(v) or v <= 1e-9 for v in lengths):
        return None
    if any(
        abs(sum(edges[i][k] * edges[(i + 1) % 4][k] for k in range(3)))
        > 1e-8 * lengths[i] * lengths[(i + 1) % 4]
        for i in range(4)
    ):
        return None
    if any(
        abs(edges[0][k] + edges[2][k]) > 1e-8 or abs(edges[1][k] + edges[3][k]) > 1e-8
        for k in range(3)
    ):
        return None
    return lengths[0] * 1000, lengths[1] * 1000


def build_fabrication(
    construction: ConstructionPlan,
    *,
    allow_synthetic: bool = False,
    sheet_width_mm: float = 1000.0,
    sheet_height_mm: float = 1000.0,
    tape_length_mm: float = 5000.0,
):
    """Return plan, actual report, action bindings and explicit scope blockers.

    Resource overrides exist for deterministic diagnostic tests; they are never
    sized from the requested design. The default fixed sheet is 1000x1000x2 mm,
    with 5000 mm of 25 mm tape, 2 mm kerf, 4 mm margins and 80 mm per joint.
    """
    if not allow_synthetic:
        return (
            None,
            None,
            (),
            (
                "Explicit synthetic-resource opt-in is required; production stock and process capture are not implemented by this adapter.",
            ),
        )
    if any(
        not math.isfinite(v) or v <= 0
        for v in (sheet_width_mm, sheet_height_mm, tape_length_mm)
    ):
        raise ValueError("Diagnostic resource dimensions must be positive and finite")
    target = construction.request.target
    assembly = target.assembly
    version_id = (
        "fab-version-"
        + hashlib.sha256(
            json.dumps(
                [
                    construction.target_hash,
                    sheet_width_mm,
                    sheet_height_mm,
                    tape_length_mm,
                    "synthetic-rectangular-construction-v1",
                ]
            ).encode()
        ).hexdigest()[:32]
    )
    sizes = {}
    for part in assembly.parts:
        size = _rectangle(part.facets[0]) if len(part.facets) == 1 else None
        if size is None:
            return (
                None,
                None,
                (),
                (
                    f"{part.part_id}: fabrication currently supports one rectangular panel per source part; polygon cuts and folded multi-facet stock need explicit compiler operations.",
                ),
            )
        sizes[part.part_id] = size
    facets = {f.facet_id: (p.part_id, f) for p in assembly.parts for f in p.facets}
    for joint in assembly.joints:
        for edge in (joint.first, joint.second):
            facet = facets[edge.facet_id][1]
            length = (
                _length(
                    facet.vertices_local[edge.edge_index],
                    facet.vertices_local[
                        (edge.edge_index + 1) % len(facet.vertices_local)
                    ],
                )
                * 1000
            )
            if length < 80 - 1e-8:
                return (
                    None,
                    None,
                    (),
                    (
                        f"{joint.joint_id}: the declared 80 mm demo tape segment cannot fit this edge; supply a supported process rather than inventing a shorter calibrated joint.",
                    ),
                )

    used = {p.part_id for p in assembly.parts} | {j.joint_id for j in assembly.joints}

    def identifier(name):
        value = f"fab-{construction.target_hash[:12]}-{name}"
        while value in used:
            value += "x"
        used.add(value)
        return value

    def measured(value, unit="mm"):
        # Deliberately synthetic fixture confirmation for compiler execution;
        # the associated evidence is never user-confirmed physical evidence.
        return m.Measurement(
            value=value, unit=unit, source="calculated", confirmed=True
        )

    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    sheet_id, region_id, tape_id = (identifier(n) for n in ("sheet", "region", "tape"))
    stocks = (
        m.Stock(
            id=sheet_id,
            kind="sheet",
            material="cardboard",
            width_mm=measured(sheet_width_mm),
            height_mm=measured(sheet_height_mm),
            thickness_mm=measured(2),
            remaining_length_mm=unknown,
            condition="usable",
            usable_regions=(
                m.Region(
                    id=region_id,
                    geometry=m.Rect(
                        x=0, y=0, width=sheet_width_mm, height=sheet_height_mm
                    ),
                ),
            ),
        ),
        m.Stock(
            id=tape_id,
            kind="tape",
            material="other_supported",
            width_mm=measured(25),
            height_mm=unknown,
            thickness_mm=unknown,
            remaining_length_mm=measured(tape_length_mm),
            condition="usable",
        ),
    )
    evidence = m.Evidence(
        id=identifier("process-evidence"),
        project_id=assembly.project_id,
        version_id=version_id,
        kind="measurement",
        provenance="synthetic_fixture",
        recorded_at=NOW,
        description=LABEL,
        verification_state="unknown",
    )
    process = CutProcess(kerf_min_mm=2, edge_margin_min_mm=4, evidence=(evidence,))
    profile = m.JointProfile(
        id=identifier("tape-profile"),
        strategy="tape",
        status="tested",
        material="cardboard",
        thickness_min_mm=2,
        thickness_max_mm=2,
        tolerated_error_mm=2,
        test_evidence_ids=(evidence.id,),
        limitations=(
            LABEL,
            "80 mm tape along each declared edge; actual access, overlap, grip and joint strength remain unverified.",
        ),
    )
    parts = []
    x, y, row_height = 4.0, 4.0, 0.0
    for part in assembly.parts:
        width, height = sizes[part.part_id]
        if x > 4 and x + width > sheet_width_mm - 4:
            x, y, row_height = 4.0, y + row_height + 2, 0.0
        parts.append(
            m.Part(
                id=part.part_id,
                source_stock_id=sheet_id,
                source_region_id=region_id,
                geometry=m.Rect(x=x, y=y, width=width, height=height),
                condition="usable",
            )
        )
        x += width + 2
        row_height = max(row_height, height)
    joints = tuple(
        m.Joint(
            id=j.joint_id,
            profile_id=profile.id,
            part_ids=(facets[j.first.facet_id][0], facets[j.second.facet_id][0]),
            confirmed_accessible=True,
        )
        for j in assembly.joints
    )
    cut_id = identifier("cut-panels")
    operations = [
        m.CutRect(
            id=cut_id,
            type="cut_rect",
            stock_ids=(sheet_id,),
            expected_state_id=identifier("cut-state"),
            preconditions=m.Preconditions(
                safe_tools_confirmed=True, human_checks=(LABEL,)
            ),
            effects=m.Effects(
                created_part_ids=tuple(p.id for p in parts),
                consumed_region_ids=(region_id,),
            ),
            args=m.CutRectArgs(
                stock_id=sheet_id,
                source_region_id=region_id,
                child_part_ids=tuple(p.id for p in parts),
                kerf_mm=2,
                edge_margin_mm=4,
            ),
        )
    ]
    checkpoints, bindings, step_ops = [], [], {}
    first_place = True
    for step in construction.steps:
        op_id = identifier(f"operation-{step.index}")
        dependencies = tuple(
            dict.fromkeys((cut_id, *(step_ops[s] for s in step.depends_on_step_ids)))
        )
        if step.action == "join":
            joint = next(j for j in joints if j.id == step.joint_id)
            operation = m.TapeJoint(
                id=op_id,
                type="tape_joint",
                reversible="lossy",
                part_ids=joint.part_ids,
                stock_ids=(tape_id,),
                depends_on=dependencies,
                expected_state_id=identifier(f"state-{step.index}"),
                preconditions=m.Preconditions(
                    accessible_part_ids=joint.part_ids,
                    human_checks=(
                        LABEL,
                        "Confirm temporary support, edge access and actual grip before joining.",
                    ),
                ),
                effects=m.Effects(attached_joint_ids=(joint.id,)),
                args=m.ConsumableJointArgs(
                    joint_id=joint.id, stock_id=tape_id, length_mm=80
                ),
            )
            subject = joint.id
        else:
            subject = step.part_ids[0] if step.action == "place" else "assembly"
            checkpoint_id = identifier(f"checkpoint-{step.index}")
            operation = m.Inspect(
                id=op_id,
                type="inspect",
                part_ids=step.part_ids,
                depends_on=dependencies,
                expected_state_id=identifier(f"state-{step.index}"),
                preconditions=m.Preconditions(
                    human_checks=(
                        LABEL,
                        "Inspection does not record placement, strength or self-support.",
                    )
                ),
                effects=m.Effects(),
                args=m.InspectArgs(
                    target_ids=step.part_ids,
                    checkpoint_id=checkpoint_id,
                    method="ruler",
                ),
            )
            checkpoints.append(
                m.Checkpoint(
                    id=checkpoint_id,
                    after_operation_id=op_id,
                    method="ruler",
                    description="Inspect prepared panel dimensions and condition; no physical pass is inferred.",
                )
            )
            if step.action == "place" and first_place:
                bindings.append(
                    ConstructionOperationBinding(
                        action="place", subject_id=subject, operation_id=cut_id
                    )
                )
                first_place = False
        operations.append(operation)
        step_ops[step.step_id] = op_id
        bindings.append(
            ConstructionOperationBinding(
                action=step.action, subject_id=subject, operation_id=op_id
            )
        )
    plan = m.BuildPlan(
        project_id=assembly.project_id,
        version_id=version_id,
        status="draft",
        stocks=stocks,
        parts=tuple(parts),
        joint_profiles=(profile,),
        joints=joints,
        operations=tuple(operations),
        checkpoints=tuple(checkpoints),
        constraints=m.Constraints(
            device_mass_g=m.Measurement(
                value=None, unit="g", source="unknown", confirmed=False
            ),
            support_angle_deg=m.Measurement(
                value=None, unit="deg", source="unknown", confirmed=False
            ),
            max_footprint_width_mm=measured(sheet_width_mm),
            max_footprint_height_mm=measured(sheet_height_mm),
            allowed_profile_ids=(profile.id,),
        ),
        compiler_version="synthetic-rectangular-construction-v1",
        created_at=NOW,
    )
    report = fabrication_report(
        FabricationInput(
            project_id=assembly.project_id,
            inventory_revision_id=target.snapshot.inventory_revision,
            lineage=(VersionHistory(plan=plan),),
            remaining_stock=stocks,
            declared_tools=("ruler", "scissors"),
            profile_evidence=(evidence,),
        ),
        process=process,
        allow_synthetic=True,
    )
    return plan, report, tuple(bindings), ()
