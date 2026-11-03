"""Generate bounded assembly-state proposals from a supplied target joint graph.

This is neither a fabrication scheduler nor a trajectory/collision planner. It
proposes positions and graph connections, then evaluates every resulting state
using the same canonical producer. Unknown support is never invented as a jig.
"""

import hashlib
import json

from forma_domain.construction_plan import (
    ConstructionPlan,
    ConstructionRequest,
    ConstructionStep,
)
from forma_domain.generic_assembly import GenericAssemblyRequest
from forma_stability.generic_assembly import evaluate_assembly

VERSION = "target-graph-construction-v1"


def bind_operations(plan: ConstructionPlan, bindings) -> ConstructionPlan:
    """Attach externally authenticated associations without recalculating physics.

    This validates the generated action subject, not a BuildPlan operation's
    permissions or existence. The fabrication bridge performs that validation.
    """
    request = ConstructionRequest(
        target=plan.request.target, operation_bindings=bindings
    )
    subjects = {
        (
            s.action,
            s.joint_id
            if s.action == "join"
            else s.part_ids[0]
            if s.action == "place"
            else "assembly",
        )
        for s in plan.steps
    }
    mapped = {}
    seen = set()
    for binding in request.operation_bindings:
        key = (binding.action, binding.subject_id)
        if key not in subjects or (key, binding.operation_id) in seen:
            raise ValueError(
                "Operation bindings must uniquely reference a generated action's subject"
            )
        seen.add((key, binding.operation_id))
        mapped.setdefault(key, []).append(binding.operation_id)
    steps = []
    for step in plan.steps:
        subject = (
            step.joint_id
            if step.action == "join"
            else step.part_ids[0]
            if step.action == "place"
            else "assembly"
        )
        steps.append(
            step.model_copy(
                update=dict(
                    operation_ids=tuple(sorted(mapped.get((step.action, subject), [])))
                )
            )
        )
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return plan.model_copy(
        update=dict(request=request, target_hash=digest, steps=tuple(steps))
    )


def generate_construction(request: ConstructionRequest) -> ConstructionPlan:
    target = request.target
    # Canonical validation and final-state mechanics remain authoritative. A
    # failed target is still useful for diagnosis, but never becomes approval.
    final = evaluate_assembly(target)
    assembly = target.assembly
    part_ids = {p.part_id for p in assembly.parts}
    joints = {j.joint_id: j for j in assembly.joints}
    if set(final.present_part_ids) != part_ids or set(final.active_joint_ids) != set(
        joints
    ):
        raise ValueError(
            "The construction target must include all declared source parts and joints"
        )
    owners = {f.facet_id: p.part_id for p in assembly.parts for f in p.facets}
    joint_parts = {
        jid: {owners[j.first.facet_id], owners[j.second.facet_id]}
        for jid, j in joints.items()
    }
    bindings = {}
    seen_bindings = set()
    for binding in request.operation_bindings:
        key = (binding.action, binding.subject_id)
        valid = (
            binding.subject_id in part_ids
            if binding.action == "place"
            else binding.subject_id in joints
            if binding.action == "join"
            else binding.subject_id == "assembly"
        )
        if not valid or (key, binding.operation_id) in seen_bindings:
            raise ValueError(
                "Operation bindings must uniquely reference a generated action's subject"
            )
        seen_bindings.add((key, binding.operation_id))
        bindings.setdefault(key, []).append(binding.operation_id)
    # Explicit supplied contact gives a root preference, not evidence that the
    # body can support itself: the generated state is evaluated below.
    contact_parts = {
        p.part_id
        for p in final.snapshot.parts
        if p.contacts
        and len(p.facet_poses)
        == len(next(a.facets for a in assembly.parts if a.part_id == p.part_id))
    }
    placed = set()
    joined = set()
    place_steps = {}
    join_steps = {}
    steps = []
    requested_checks = tuple(
        dict.fromkeys(("support", "tip", *target.policy.required_check_types))
    )

    def append(action, subject, members, joint_id, dependencies, instruction):
        index = len(steps)
        sid = f"construction-{index + 1}"
        full = placed == part_ids and joined == set(joints)
        stage = dict(
            stage_id=sid,
            label=f"{index + 1}. {instruction}",
            present_part_ids=sorted(placed),
            active_joint_ids=sorted(joined),
        )
        snapshot = target.snapshot.model_dump(mode="python")
        snapshot["parts"] = [p for p in target.snapshot.parts if p.part_id in placed]
        snapshot["rigid_joint_ids"] = [
            jid for jid in target.snapshot.rigid_joint_ids if jid in joined
        ]
        snapshot["component_loads"] = target.snapshot.component_loads if full else ()
        stage_request = GenericAssemblyRequest.model_validate(
            dict(
                assembly={**assembly.model_dump(mode="python"), "stages": [stage]},
                stage_id=sid,
                snapshot=snapshot,
                policy={
                    **target.policy.model_dump(mode="python"),
                    "required_check_types": requested_checks,
                },
                uniform_mass_part_ids=[
                    pid for pid in target.uniform_mass_part_ids if pid in placed
                ],
                full_face_contact_facet_ids=[
                    fid
                    for fid in target.full_face_contact_facet_ids
                    if owners[fid] in placed
                ],
            )
        )
        analysis = evaluate_assembly(stage_request)
        unresolved = list(analysis.blockers)
        support_established = len(analysis.reports) == len(analysis.component_part_ids)
        for report in analysis.reports:
            for check in report.results:
                if (
                    check.check_type in ("support", "tip")
                    and check.status != "modeled_pass"
                ):
                    support_established = False
                if check.status not in ("modeled_pass", "not_applicable"):
                    unresolved.append(
                        f"{check.case_id}/{check.check_type}: {check.status}. {check.explanation}"
                    )
        if not support_established:
            unresolved.insert(
                0,
                "Self-support is not established at this stage. Temporary support or a different placement must be supplied and checked; none is invented by this proposal.",
            )
        if target.snapshot.component_loads and not full:
            unresolved.append(
                "Final assembly reaction/strength/beam demands are not transferred to a changed intermediate load path; stage-specific values remain required."
            )
        # The enum/check matrix caps the typical count at 80. Preserve a bounded
        # actionable list rather than an unbounded repetition of shared warnings.
        unresolved = list(dict.fromkeys(unresolved))[:128]
        step = ConstructionStep(
            step_id=sid,
            index=index,
            action=action,
            part_ids=tuple(sorted(members)),
            joint_id=joint_id,
            depends_on_step_ids=tuple(sorted(set(dependencies))),
            instruction=instruction,
            operation_ids=tuple(sorted(bindings.get((action, subject), []))),
            analysis=analysis,
            requires_external_support=not support_established,
            unresolved_predicates=tuple(unresolved),
        )
        steps.append(step)
        return sid

    while placed != part_ids:
        remaining = part_ids - placed
        adjacent = {
            pid
            for pid in remaining
            if any(pid in pair and pair & placed for pair in joint_parts.values())
        }
        choices = adjacent or remaining
        pid = min(choices, key=lambda p: (p not in contact_parts, p))
        placed.add(pid)
        place_steps[pid] = append(
            "place",
            pid,
            {pid},
            None,
            (),
            f"Position source part {pid} at its supplied target pose; check its contact and support before releasing it.",
        )
        for jid in sorted(set(joints) - joined):
            members = joint_parts[jid]
            if members <= placed:
                joined.add(jid)
                join_steps[jid] = append(
                    "join",
                    jid,
                    members,
                    jid,
                    [place_steps[p] for p in members],
                    f"Connect declared joint {jid} between {' and '.join(sorted(members))}; its connector method and access must pass fabrication review.",
                )
    append(
        "inspect",
        "assembly",
        part_ids,
        None,
        tuple(place_steps.values()) + tuple(join_steps.values()),
        "Inspect the complete proposed assembly and perform the required real-world checks; modeled results do not record a physical pass.",
    )
    digest = hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return ConstructionPlan(
        generator_version=VERSION,
        target_hash=digest,
        request=request,
        steps=tuple(steps),
        limitations=(
            "Generated positions and connections are hypothetical assembly proposals, not cutting instructions, fabrication readiness, collision-free motions or completed work.",
            "Unplaced parts are excluded only from the proposed assembly load model. They are not claimed to be uncut, nonexistent or available stock.",
            "Supplied target poses and contacts are reused explicitly; temporary holding, tools, connector consumption, accessibility and strength are not invented.",
            "The fabrication engine remains authoritative for a real BuildPlan's operation dependencies and readiness. Operation associations alone grant no permission.",
            "Each physical analysis describes the exact ordered proposal prefix shown. A different action order requires a new stage analysis; endpoint dependencies are not permission to reuse a different prefix's result.",
        ),
    )
