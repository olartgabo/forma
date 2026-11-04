"""Planned display references, never physical poses or stability inputs."""

from math import dist

from forma_domain.assembly_view_contracts import PlannedOperationIllustration
from forma_domain.models import BuildPlan
from forma_stability.geometry import project_nominal_geometry


def planned_operation_illustration(plan: BuildPlan, operation_id: str):
    reference = project_nominal_geometry(plan)
    present, joints, folded = set(), set(), set()
    found = False
    for op in plan.operations:
        present.update(op.effects.created_part_ids)
        joints.difference_update(op.effects.detached_joint_ids)
        joints.update(op.effects.attached_joint_ids)
        if op.type == "fold":
            folded.add(op.args.feature_id)
        if op.id == operation_id:
            found = True
            break
    if not found:
        raise ValueError("Selected operation is not in this plan")
    facets = []
    flattened = False
    for facet in reference.facets:
        if facet.part_id not in present:
            continue
        if facet.feature_id and facet.feature_id not in folded:
            # The supported canonical stand supplies a shared fold edge and
            # rectangular adjacent faces. Extend the main face across that
            # edge by the lip's own length, in the same nominal target plane.
            face = next(
                f
                for f in reference.facets
                if f.part_id == facet.part_id and f.feature_id is None
            )
            a, b, _, d = face.vertices
            lip_a, lip_b, _, lip_d = facet.vertices
            axes = ("x", "y", "z")
            vector = [getattr(d, k) - getattr(a, k) for k in axes]
            length = dist(
                tuple(getattr(a, k) for k in axes), tuple(getattr(d, k) for k in axes)
            )
            lip_length = dist(
                tuple(getattr(lip_a, k) for k in axes),
                tuple(getattr(lip_d, k) for k in axes),
            )
            shift = [-v * lip_length / length for v in vector]
            end_a = lip_a.model_copy(
                update=dict(
                    zip(
                        axes, (getattr(lip_a, k) + shift[i] for i, k in enumerate(axes))
                    )
                )
            )
            end_b = lip_b.model_copy(
                update=dict(
                    zip(
                        axes, (getattr(lip_b, k) + shift[i] for i, k in enumerate(axes))
                    )
                )
            )
            vertices = (lip_a, lip_b, end_b, end_a)
            centroid = lip_a.model_copy(
                update={k: sum(getattr(p, k) for p in vertices) / 4 for k in axes}
            )
            facet = facet.model_copy(
                update={"vertices": vertices, "centroid": centroid}
            )
            flattened = True
        facets.append(facet)
    notes = [
        "Planned target positions after this operation; not actual positions, contacts, stability or completed work."
    ]
    if flattened:
        notes.append(
            "The not-yet-folded face is shown flat in the target panel plane; placement is illustrative."
        )
    return PlannedOperationIllustration(
        operation_id=operation_id,
        present_part_ids=tuple(sorted(present)),
        planned_joint_ids=tuple(sorted(joints)),
        facets=facets,
        notes=tuple(notes),
    )
