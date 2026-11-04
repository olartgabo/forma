"""Consented SAM boxes in source pixels; no material or physical authority."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from forma_api.model_gateway import Box, MetaGateway
from forma_api.projects import Key
from forma_api.provider_diagnostics import ProviderUsage
from forma_domain.models import ID, Record


class PhotoLocalizationRequest(Record):
    media_id: ID
    expected_revision_id: ID
    idempotency_key: Key
    concept: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[\w -]+$")]
    provider_transfer_consented: StrictBool = False

    @field_validator("concept")
    @classmethod
    def one_concept(cls, value):
        if not value.strip() or " and " in value.lower():
            raise ValueError("Name one material or object")
        return value


class PhotoLocalizationResult(Record):
    project_id: ID
    revision_id: ID
    media_id: ID
    width_px: int
    height_px: int
    boxes: tuple[Box, ...] = Field(max_length=32)
    model: str
    usage: ProviderUsage
    physical_status: Literal["unverified_photo_annotation"] = (
        "unverified_photo_annotation"
    )
    replayed: bool = False


def default_gateway_factory():
    gateway = MetaGateway.from_env()
    # Never silently retry a paid image request, including transport failures.
    gateway.max_retries = 0
    return gateway
