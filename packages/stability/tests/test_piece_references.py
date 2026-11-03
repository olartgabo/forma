"""Stable addresses connect proposed names to authoritative source geometry."""

import pytest
from forma_stability.construction import bind_operations, generate_construction
from forma_stability.generic_examples import assembly_example
from forma_stability.piece_references import build_piece_catalog, geometry_class
from pydantic import ValidationError

from forma_domain.construction_plan import (
    ConstructionOperationBinding,
    ConstructionRequest,
)
from forma_domain.generic_assembly import (
    AssemblyFacet,
    AssemblyPart,
    GenericAssemblyRequest,
)
from forma_domain.piece_references import PieceAnnotation


def annotation(part_id="deck", name="Base", source="user", **kwargs):
    return PieceAnnotation(part_id=part_id, display_name=name, source=source, **kwargs)


def facet(points, name="face"):
    return AssemblyFacet(
        facet_id=name,
        vertices_local=[dict(zip(("x", "y", "z"), p)) for p in points],
    )


@pytest.mark.parametrize(
    "points,expected",
    [
        ([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "triangle"),
        ([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)], "rectangle"),
        ([(0, 0, 0), (1, 1, 0), (1, 1, 2), (0, 0, 2)], "rectangle"),
        ([(0, 0, 0), (2, 0, 0), (1, 1, 0), (0, 1, 0)], "convex_polygon"),
        (
            [(0, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)],
            "concave_polygon",
        ),
    ],
)
def test_shape_class_is_computed_in_panel_plane_and_ignores_winding(points, expected):
    for sequence in (points, list(reversed(points))):
        assert (
            geometry_class(AssemblyPart(part_id="p", facets=(facet(sequence),)))
            == expected
        )


def test_multifacet_class_and_invalid_geometry_use_canonical_validator():
    first = facet([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    second = facet([(0, 0, 0), (1, 0, 0), (0, 0, 1)], "other")
    assert (
        geometry_class(AssemblyPart(part_id="p", facets=(first, second)))
        == "multi_facet"
    )
    with pytest.raises(ValueError, match="planar"):
        geometry_class(
            AssemblyPart(
                part_id="p",
                facets=(facet([(0, 0, 0), (1, 0, 0), (1, 1, 1), (0, 1, 0)]),),
            )
        )


def test_references_survive_input_reorder_rename_dimensions_and_mass_change():
    target = assembly_example("box")
    original = build_piece_catalog(target.assembly)
    changed = target.model_dump(mode="json")
    changed["assembly"]["parts"].reverse()
    for part in changed["assembly"]["parts"]:
        for face in part["facets"]:
            for point in face["vertices_local"]:
                point["x"] *= 1.5
    for part in changed["snapshot"]["parts"]:
        part["mass_kg"] = 0.5
    new_target = GenericAssemblyRequest.model_validate(changed)
    labels = tuple(
        annotation(part.part_id, "Side panel") for part in target.assembly.parts
    )
    updated = build_piece_catalog(new_target.assembly, labels)
    assert [p.part_id for p in original] == [p.part_id for p in updated]
    assert [p.reference for p in original] == [p.reference for p in updated]
    assert len({p.reference for p in updated}) == len(updated)
    assert all(p.display_name == "Side panel" for p in updated)
    assert len({p.geometry_class for p in updated}) == 1


@pytest.mark.parametrize(
    "annotations", [(annotation(), annotation()), (annotation("missing"),)]
)
def test_dangling_and_duplicate_annotation_ids_rejected_at_input_boundary(annotations):
    with pytest.raises(ValidationError, match="uniquely reference"):
        ConstructionRequest(
            target=assembly_example("box"), piece_annotations=annotations
        )
    with pytest.raises(ValueError, match="uniquely reference"):
        build_piece_catalog(assembly_example("box").assembly, annotations)


def test_model_semantic_proposal_never_overrides_computed_geometry_or_physical_results():
    target = assembly_example("triangle")
    before = generate_construction(ConstructionRequest(target=target))
    proposal = annotation(
        name="Soporte izquierdo",
        source="model",
        role="brace",
        proposed_classification="circle",
    )
    after = generate_construction(
        ConstructionRequest(target=target, piece_annotations=(proposal,))
    )
    piece = after.piece_catalog[0]
    assert piece.geometry_class == "triangle"
    assert piece.annotation == proposal
    assert piece.role == "brace"
    assert piece.reference == before.piece_catalog[0].reference
    assert piece.reference in after.steps[0].instruction
    assert proposal.display_name in after.steps[0].instruction
    assert after.steps[0].part_ids == ("deck",)
    assert (
        after.steps[-1].analysis.world_overlays
        == before.steps[-1].analysis.world_overlays
    )
    assert all(not s.analysis.physical_evidence_ids for s in after.steps)
    binding = ConstructionOperationBinding(
        action="place", subject_id="deck", operation_id="cut-panel"
    )
    bound = bind_operations(after, (binding,))
    assert bound.piece_catalog == after.piece_catalog
    assert bound.request.piece_annotations == (proposal,)
    assert bound.steps[0].operation_ids == ("cut-panel",)


@pytest.mark.parametrize(
    "name",
    ["", " ", " Base", "Base ", "Base\nnext", "Base\x00", "Base\u202eevil", "x" * 121],
)
def test_ambiguous_control_and_unbounded_labels_rejected(name):
    with pytest.raises(ValidationError):
        annotation(name=name)


def test_unicode_and_markup_remain_plain_data_not_identity_or_instructions():
    target = assembly_example("triangle")
    proposed = annotation(name='<script>alert("x")</script> — 左側')
    plan = generate_construction(
        ConstructionRequest(target=target, piece_annotations=(proposed,))
    )
    assert plan.piece_catalog[0].display_name == proposed.display_name
    assert plan.steps[0].part_ids == ("deck",)
    assert plan.request.target == target
    with pytest.raises(ValidationError):
        PieceAnnotation.model_validate({**proposed.model_dump(), "confirmed": True})


def test_reference_collision_is_rejected_without_renumbering(monkeypatch):
    import forma_stability.piece_references as module

    monkeypatch.setattr(module, "piece_reference", lambda _: "P-000000000000")
    with pytest.raises(ValueError, match="collision"):
        module.build_piece_catalog(assembly_example("box").assembly)
