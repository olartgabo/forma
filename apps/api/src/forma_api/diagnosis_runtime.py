"""Server-only read-only failure-photo diagnosis runtime. Never mutates state."""

import time
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StringConstraints, model_validator

from forma_api.intake_runtime import (
    MAX_PROVIDER_IMAGE_BYTES,
    SUPPORTED_IMAGE_TYPES,
)
from forma_api.intake_runtime import (
    gateway_error_details as _shared_gateway_error_details,
)
from forma_api.model_gateway import GatewayError, ImageInput, MetaGateway
from forma_api.proposal_prompts import instructions
from forma_domain.models import ID, DiagnosisProposal, Record, Stock, Text

MAX_REPORTED_PROBLEM_LENGTH = 1000

DIAGNOSIS_SYSTEM_PROMPT = (
    instructions("diagnose")
    + " This is a read-only photo observation. The reported_problem in"
    + " untrusted_context is a user report, not an observed fact; keep it"
    + " distinct from visible_observations. Do not propose repair actions,"
    + " plan changes, inventory changes or physical test results. No completion"
    + " history is supplied or assumed. When active_plan is null, there is no"
    + " plan, calibrated process or current operation: affected_ids must be"
    + " empty and failure_type must be unknown unless the photo alone clearly"
    + " supports a listed type without referencing any plan item. When"
    + " active_plan is present, affected_ids may only use its"
    + " allowed_affected_ids. Hidden strength, exact scale and test outcomes"
    + " cannot be observed from a photo; ask targeted questions or"
    + " measurements when evidence is insufficient."
)

DIAGNOSIS_PROMPT = (
    "Diagnose the failure in the consented photo using only the supplied "
    "saved context. Separate visible observations, hypotheses and questions "
    "or measurements, and keep the user-reported problem distinct from what "
    "is visible."
)


class DiagnosisRequest(Record):
    media_id: ID
    expected_revision_id: ID
    reported_problem: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_REPORTED_PROBLEM_LENGTH,
        ),
    ]
    provider_transfer_consented: StrictBool = False
    expected_active_version_id: ID | None = None
    current_operation_id: ID | None = None

    @model_validator(mode="after")
    def paired_operation_context(self):
        if (self.expected_active_version_id is None) != (
            self.current_operation_id is None
        ):
            raise ValueError(
                "expected_active_version_id and current_operation_id must be supplied together"
            )
        return self


class DiagnosisDiagnostics(Record):
    status: Literal["ok"]
    model: str = Field(min_length=1, max_length=80)
    elapsed_ms: int = Field(ge=0)


class DiagnosisErrorResponse(Record):
    code: Literal[
        "validation_error",
        "not_found",
        "stale_version",
        "consent_required",
        "provider_not_configured",
        "provider_authentication",
        "access_denied",
        "rate_limit",
        "timeout",
        "network_error",
        "invalid_response",
        "provider_http_error",
        "provider_error",
    ]
    message: Text


class DiagnosisResult(Record):
    project_id: ID
    revision_id: ID
    media_id: ID
    active_version_id: ID | None = None
    current_operation_id: ID | None = None
    diagnosis: DiagnosisProposal
    diagnostics: DiagnosisDiagnostics


def default_gateway_factory() -> MetaGateway:
    return MetaGateway.from_env()


def allowed_affected_ids(plan) -> set[str]:
    if plan is None:
        return set()
    ids = {plan.version_id}
    ids.update(stock.id for stock in plan.stocks)
    ids.update(part.id for part in plan.parts)
    ids.update(feature.id for part in plan.parts for feature in part.features)
    ids.update(joint.id for joint in plan.joints)
    ids.update(operation.id for operation in plan.operations)
    ids.update(checkpoint.id for checkpoint in plan.checkpoints)
    return ids


def build_context(
    *,
    project_id: str,
    revision_id: str,
    project_goal: str,
    reported_problem: str,
    stocks: tuple[Stock, ...],
    plan=None,
    current_operation_id: str | None = None,
) -> dict:
    active_plan = None
    if plan is not None:
        operation = next(
            (item for item in plan.operations if item.id == current_operation_id),
            None,
        )
        active_plan = {
            "version_id": plan.version_id,
            "family": plan.family,
            "status": plan.status,
            "current_operation": (
                {
                    "id": operation.id,
                    "type": operation.type,
                    "part_ids": list(operation.part_ids),
                    "stock_ids": list(operation.stock_ids),
                    "depends_on": list(operation.depends_on),
                    "expected_state_id": operation.expected_state_id,
                    "requires_user_confirmation": operation.requires_user_confirmation,
                }
                if operation is not None
                else None
            ),
            "operations": [
                {
                    "id": item.id,
                    "type": item.type,
                    "part_ids": list(item.part_ids),
                    "stock_ids": list(item.stock_ids),
                }
                for item in plan.operations
            ],
            "parts": [
                {
                    "id": part.id,
                    "source_stock_id": part.source_stock_id,
                    "condition": part.condition,
                    "feature_ids": [feature.id for feature in part.features],
                }
                for part in plan.parts
            ],
            "joints": [
                {
                    "id": joint.id,
                    "profile_id": joint.profile_id,
                    "part_ids": list(joint.part_ids),
                    "interface_feature_ids": list(joint.interface_feature_ids),
                }
                for joint in plan.joints
            ],
            "checkpoints": [
                {
                    "id": checkpoint.id,
                    "after_operation_id": checkpoint.after_operation_id,
                    "method": checkpoint.method,
                    "description": checkpoint.description,
                }
                for checkpoint in plan.checkpoints
            ],
            "allowed_affected_ids": sorted(allowed_affected_ids(plan)),
        }
    return {
        "project_id": project_id,
        "inventory_revision_id": revision_id,
        "project_goal": project_goal,
        "reported_problem": reported_problem,
        "reported_problem_is_observed_fact": False,
        "saved_inventory": [stock.model_dump(mode="json") for stock in stocks],
        "active_plan": active_plan,
        "completion_history_supplied": False,
    }


def validate_diagnosis(proposal: DiagnosisProposal, *, plan=None) -> DiagnosisProposal:
    allowed = allowed_affected_ids(plan)
    if len(set(proposal.affected_ids)) != len(proposal.affected_ids):
        raise GatewayError("invalid_diagnosis_reference")
    if not set(proposal.affected_ids) <= allowed:
        raise GatewayError("invalid_diagnosis_reference")
    return proposal


def diagnose_photo(
    gateway: MetaGateway,
    *,
    image_data: bytes,
    content_type: str,
    context: dict,
    plan=None,
) -> tuple[DiagnosisProposal, DiagnosisDiagnostics]:
    """One bounded Muse call through the gateway; no tool and no retries."""

    if content_type not in SUPPORTED_IMAGE_TYPES:
        raise GatewayError("invalid_image")
    if not 0 < len(image_data) <= MAX_PROVIDER_IMAGE_BYTES:
        raise GatewayError("invalid_image")
    start = time.monotonic()
    proposal = gateway.propose(
        DIAGNOSIS_PROMPT,
        DiagnosisProposal,
        image=ImageInput(image_data, content_type, True),  # type: ignore[arg-type]
        system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
        context=context,
    )
    validate_diagnosis(proposal, plan=plan)
    elapsed_ms = round((time.monotonic() - start) * 1000)
    traces = getattr(gateway, "traces", [])
    if traces:
        elapsed_ms = traces[-1].elapsed_ms
    model = str(getattr(gateway, "spark", "unknown"))[:80] or "unknown"
    return proposal, DiagnosisDiagnostics(
        status="ok", model=model, elapsed_ms=elapsed_ms
    )


def gateway_error_details(code: str) -> tuple[int, str, str]:
    if code == "invalid_diagnosis_reference":
        return (
            502,
            "invalid_response",
            "Model provider returned an unusable response; retry",
        )
    return _shared_gateway_error_details(code)
