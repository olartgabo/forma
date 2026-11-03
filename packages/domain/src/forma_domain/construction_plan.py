"""Generated physical assembly proposals, separate from fabrication readiness."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .generic_assembly import GenericAssemblyRequest, GenericAssemblyResult
from .models import ID, Record, Text
from .piece_references import PieceAnnotation, PieceReference
from .stability_contracts import ContentHash

ConstructionAction = Literal["place", "join", "inspect"]


class ConstructionOperationBinding(Record):
    """External operation association; the fabrication adapter must authenticate it."""

    action: ConstructionAction
    subject_id: ID
    operation_id: ID


class ConstructionRequest(Record):
    target: GenericAssemblyRequest
    piece_annotations: tuple[PieceAnnotation, ...] = Field(default=(), max_length=16)
    operation_bindings: tuple[ConstructionOperationBinding, ...] = Field(
        default=(), max_length=64
    )

    @model_validator(mode="after")
    def annotation_references(self):
        ids = [annotation.part_id for annotation in self.piece_annotations]
        if len(set(ids)) != len(ids) or not set(ids) <= {
            part.part_id for part in self.target.assembly.parts
        }:
            raise ValueError(
                "Piece annotations must uniquely reference existing part IDs"
            )
        return self


class ConstructionStep(Record):
    step_id: ID
    index: Annotated[int, Field(strict=True, ge=0, le=63)]
    action: ConstructionAction
    part_ids: tuple[ID, ...] = Field(max_length=16)
    joint_id: ID | None
    depends_on_step_ids: tuple[ID, ...] = Field(max_length=64)
    instruction: Text
    operation_ids: tuple[ID, ...] = Field(max_length=64)
    analysis: GenericAssemblyResult
    requires_external_support: bool
    unresolved_predicates: tuple[Text, ...] = Field(max_length=128)


class ConstructionPlan(Record):
    generator_version: Text
    target_hash: ContentHash
    request: ConstructionRequest
    piece_catalog: tuple[PieceReference, ...] = Field(min_length=1, max_length=16)
    steps: tuple[ConstructionStep, ...] = Field(min_length=1, max_length=64)
    limitations: tuple[Text, ...] = Field(min_length=1, max_length=32)
