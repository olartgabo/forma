"""Generated physical assembly proposals, separate from fabrication readiness."""

from typing import Annotated, Literal

from pydantic import Field

from .generic_assembly import GenericAssemblyRequest, GenericAssemblyResult
from .models import ID, Record, Text
from .stability_contracts import ContentHash

ConstructionAction = Literal["place", "join", "inspect"]


class ConstructionOperationBinding(Record):
    """External operation association; the fabrication adapter must authenticate it."""

    action: ConstructionAction
    subject_id: ID
    operation_id: ID


class ConstructionRequest(Record):
    target: GenericAssemblyRequest
    operation_bindings: tuple[ConstructionOperationBinding, ...] = Field(
        default=(), max_length=64
    )


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
    steps: tuple[ConstructionStep, ...] = Field(min_length=1, max_length=64)
    limitations: tuple[Text, ...] = Field(min_length=1, max_length=32)
