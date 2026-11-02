import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from forma_api.model_gateway import DEFAULT_SAM_MODEL, DEFAULT_SPARK_MODEL, MODEL_ID_RE
from forma_domain.models import Record

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ProviderStatusResponse(Record):
    configured: bool
    model: str = Field(min_length=1, max_length=80)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report process liveness, without asserting provider or storage readiness."""
    return HealthResponse(status="ok")


@router.get("/provider/status", response_model=ProviderStatusResponse)
def provider_status() -> ProviderStatusResponse:
    """Check local key/model configuration without constructing a gateway."""
    candidate = os.environ.get("META_SPARK_MODEL", DEFAULT_SPARK_MODEL)
    sam = os.environ.get("META_SAM_MODEL", DEFAULT_SAM_MODEL)
    valid_spark = MODEL_ID_RE.fullmatch(candidate) is not None
    configured = (
        bool(os.environ.get("MODEL_API_KEY", "").strip())
        and valid_spark
        and MODEL_ID_RE.fullmatch(sam) is not None
    )
    model = candidate if valid_spark else DEFAULT_SPARK_MODEL
    return ProviderStatusResponse(configured=configured, model=model)
