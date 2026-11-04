"""Display-only projections never claim physical or mechanical results."""

import math

import pytest
from forma_stability.planned_illustration import planned_operation_illustration
from test_geometry import plan


@pytest.mark.parametrize("alternate", [False, True])
def test_cut_and_fold_use_actual_source_dimensions(alternate):
    source = plan(alternate)
    cut = planned_operation_illustration(source, source.operations[0].id)
    folded = planned_operation_illustration(source, source.operations[2].id)
    flat_lip = next(f for f in cut.facets if f.feature_id)
    folded_lip = next(f for f in folded.facets if f.feature_id)
    support = next(
        f for f in cut.facets if f.part_id == flat_lip.part_id and not f.feature_id
    )
    part = next(p for p in source.parts if p.id == flat_lip.part_id)

    def distance(a, b):
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

    assert distance(flat_lip.vertices[0], flat_lip.vertices[3]) == pytest.approx(
        (part.geometry.height - part.features[0].geometry.y) / 1000
    )
    va = [
        getattr(support.vertices[3], k) - getattr(support.vertices[0], k)
        for k in ("x", "y", "z")
    ]
    vb = [
        getattr(flat_lip.vertices[3], k) - getattr(flat_lip.vertices[0], k)
        for k in ("x", "y", "z")
    ]
    assert sum(a * b for a, b in zip(va, vb)) == pytest.approx(
        -math.sqrt(sum(a * a for a in va) * sum(b * b for b in vb))
    )
    assert flat_lip.vertices != folded_lip.vertices
    assert cut.planned_joint_ids == ()
    assert "not actual" in cut.notes[0]
