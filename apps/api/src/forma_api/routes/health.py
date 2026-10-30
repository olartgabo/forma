from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report process liveness, without asserting provider or storage readiness."""
    return HealthResponse(status="ok")
