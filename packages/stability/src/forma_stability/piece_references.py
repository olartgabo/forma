"""Read-only piece catalogue shared by model tools, construction and diagrams."""

import hashlib
import math

from forma_domain.generic_assembly import AssemblyPart, GenericAssembly
from forma_domain.piece_references import PieceAnnotation, PieceReference
from forma_stability.generic_assembly import polygon_geometry


def piece_reference(part_id: str) -> str:
    """Part identity, not name, geometry, ordering or camera, determines the reference."""
    return "P-" + hashlib.sha256(part_id.encode("utf-8")).hexdigest()[:12].upper()


def geometry_class(part: AssemblyPart) -> str:
    # Reuse the canonical polygon validation, including non-planar/invalid rejection.
    metrics = [polygon_geometry(f.vertices_local) for f in part.facets]
    if len(metrics) > 1:
        return "multi_facet"
    polygon = metrics[0][2][4]
    points = list(polygon.exterior.coords)[:-1]
    if len(points) == 3:
        return "triangle"
    if len(points) == 4:
        edges = [
            (points[(i + 1) % 4][0] - p[0], points[(i + 1) % 4][1] - p[1])
            for i, p in enumerate(points)
        ]
        if all(
            abs(a[0] * b[0] + a[1] * b[1]) <= 1e-8 * math.hypot(*a) * math.hypot(*b)
            for a, b in zip(edges, edges[1:] + edges[:1])
        ):
            return "rectangle"
    return (
        "convex_polygon"
        if polygon.convex_hull.area - polygon.area <= polygon.area * 1e-10
        else "concave_polygon"
    )


def build_piece_catalog(
    assembly: GenericAssembly, annotations: tuple[PieceAnnotation, ...] = ()
) -> tuple[PieceReference, ...]:
    """Resolve validated proposals without changing IDs, geometry or evidence.

    References are scoped to the supplied assembly/project. Duplicate friendly
    names are allowed: the stable reference is always the unambiguous address.
    """
    part_ids = {part.part_id for part in assembly.parts}
    if len(part_ids) != len(assembly.parts):
        raise ValueError("Duplicate assembly part ID")
    proposed = {annotation.part_id: annotation for annotation in annotations}
    if len(proposed) != len(annotations) or not set(proposed) <= part_ids:
        raise ValueError("Piece annotations must uniquely reference existing part IDs")
    references = [piece_reference(pid) for pid in part_ids]
    if len(set(references)) != len(references):
        raise ValueError(
            "Piece reference collision; ambiguous references are not allowed"
        )
    output = []
    for part in sorted(assembly.parts, key=lambda item: item.part_id):
        annotation = proposed.get(part.part_id)
        shape = geometry_class(part)
        output.append(
            PieceReference(
                part_id=part.part_id,
                reference=piece_reference(part.part_id),
                display_name=annotation.display_name
                if annotation
                else {
                    "triangle": "Triangular panel",
                    "rectangle": "Rectangular panel",
                    "convex_polygon": "Polygon panel",
                    "concave_polygon": "Concave panel",
                    "multi_facet": "Multi-facet piece",
                }[shape],
                geometry_class=shape,
                role=annotation.role if annotation else None,
                annotation=annotation,
            )
        )
    return tuple(output)


def piece_caption(piece: PieceReference) -> str:
    return f"{piece.reference} — {piece.display_name}"
