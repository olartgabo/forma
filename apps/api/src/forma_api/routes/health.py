import os
import re
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from forma_domain.models import Record

router = APIRouter()

DEFAULT_SPARK_MODEL = "muse-spark-1.3"
_MODEL_ID = re.compile(r"[a-z0-9.-]{1,80}")


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
    """Report only whether a provider key is configured; never call the provider."""
    configured = bool(os.environ.get("MODEL_API_KEY", "").strip())
    candidate = os.environ.get("META_SPARK_MODEL", DEFAULT_SPARK_MODEL)
    model = candidate if _MODEL_ID.fullmatch(candidate) else DEFAULT_SPARK_MODEL
    return ProviderStatusResponse(configured=configured, model=model)
