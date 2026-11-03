"""Piece labels are proposals; stable references and geometry stay authoritative."""

import unicodedata
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .models import ID, Record

PieceLabel = Annotated[str, Field(min_length=1, max_length=120)]
GeometryClass = Literal[
    "triangle", "rectangle", "convex_polygon", "concave_polygon", "multi_facet"
]


class PieceAnnotation(Record):
    """User or model naming proposal, never a measurement or an observation."""

    part_id: ID
    display_name: PieceLabel
    role: PieceLabel | None = None
    proposed_classification: PieceLabel | None = None
    source: Literal["user", "model"]

    @field_validator("display_name", "role", "proposed_classification")
    @classmethod
    def readable_label(cls, value):
        if value is None:
            return None
        if not value.strip() or value != value.strip():
            raise ValueError("Piece labels must be nonblank without outer whitespace")
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Piece labels cannot contain control or format characters")
        return value


class PieceReference(Record):
    part_id: ID
    reference: Annotated[str, Field(pattern=r"^P-[A-F0-9]{12}$")]
    display_name: PieceLabel
    geometry_class: GeometryClass
    role: PieceLabel | None = None
    annotation: PieceAnnotation | None = None
