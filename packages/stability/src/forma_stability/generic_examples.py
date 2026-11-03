"""Invented declarative examples; no measurements or fabrication instructions."""

from forma_domain.generic_assembly import GenericAssemblyRequest


def assembly_example(name="triangle"):
    """Data-only triangle, ramp and open box using the same physical producer."""
    base = [(0, 0, 0), (0.2, 0, 0), (0.2, 0.3, 0), (0, 0.3, 0)]
    definitions = {
        "triangle": {"deck": [(0, 0, 0), (0.2, 0, 0), (0.1, 0.2, 0)]},
        "concave": {
            "deck": [
                (0, 0, 0),
                (0.3, 0, 0),
                (0.3, 0.1, 0),
                (0.1, 0.1, 0),
                (0.1, 0.3, 0),
                (0, 0.3, 0),
            ]
        },
        "ramp": {
            "deck": base,
            "slope": [(0, 0, 0), (0.2, 0, 0), (0.2, 0.2, 0.2), (0, 0.2, 0.2)],
        },
        "box": {
            "deck": base,
            "front": [(0, 0, 0), (0.2, 0, 0), (0.2, 0, 0.1), (0, 0, 0.1)],
            "right": [(0.2, 0, 0), (0.2, 0.3, 0), (0.2, 0.3, 0.1), (0.2, 0, 0.1)],
            "rear": [(0.2, 0.3, 0), (0, 0.3, 0), (0, 0.3, 0.1), (0.2, 0.3, 0.1)],
            "left": [(0, 0.3, 0), (0, 0, 0), (0, 0, 0.1), (0, 0.3, 0.1)],
        },
    }
    if name not in definitions:
        raise ValueError("Choose triangle, concave, ramp or box")
    panels = definitions[name]

    def point(p):
        return dict(zip(("x", "y", "z"), (float(v) for v in p)))

    identity = dict(
        rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        translation_m=point((0, 0, 0)),
    )
    parts = [
        dict(
            part_id=pid,
            facets=[
                dict(
                    facet_id=f"{pid}-face", vertices_local=[point(p) for p in vertices]
                )
            ],
        )
        for pid, vertices in panels.items()
    ]
    joints = [
        dict(
            joint_id=f"join-{pid}",
            first=dict(facet_id="deck-face", edge_index=i),
            second=dict(facet_id=f"{pid}-face", edge_index=0),
        )
        for i, pid in enumerate(list(panels)[1:])
    ]
    stages = [
        dict(
            stage_id="base",
            label="Hypothetical base panel only",
            present_part_ids=["deck"],
            active_joint_ids=[],
        ),
        dict(
            stage_id="complete",
            label="Hypothetical full assembly",
            present_part_ids=list(panels),
            active_joint_ids=[j["joint_id"] for j in joints],
        ),
    ]
    return GenericAssemblyRequest.model_validate(
        dict(
            assembly=dict(
                project_id="generic-lab",
                plan_version_id="generic-example-v1",
                parts=parts,
                joints=joints,
                stages=stages,
            ),
            stage_id="complete",
            snapshot=dict(
                project_id="generic-lab",
                plan_version_id="generic-example-v1",
                inventory_revision="lab-not-inventory",
                history_cursor=None,
                completed_operation_ids=[],
                basis="hypothetical",
                support_frame=identity,
                gravity_world_m_s2=point((0, 0, -9.81)),
                parts=[
                    dict(
                        part_id=pid,
                        mass_kg=0.1,
                        center_of_mass_world=None,
                        facet_poses=[dict(facet_id=f"{pid}-face", transform=identity)],
                        contacts=[],
                        rigid_body_assumed=True,
                    )
                    for pid in panels
                ],
                rigid_joint_ids=[j["joint_id"] for j in joints],
                assumption_notes=[
                    "Invented 100g uniform panels, rigid joints and full base contact; no measurements or physical work."
                ],
            ),
            policy=dict(
                policy_id="generic-lab",
                version="v1",
                length_tolerance_m=1e-9,
                force_tolerance_n=1e-9,
                moment_tolerance_n_m=1e-9,
                relative_tolerance=1e-12,
                required_margin_m=0.0,
                uncertainty_method="analytic_interval",
                evaluation_budget=16,
                required_check_types=["support", "tip"],
                required_case_ids=["component-1"],
            ),
            uniform_mass_part_ids=list(panels),
            full_face_contact_facet_ids=["deck-face"],
        )
    )
