"""Server-only Muse repair proposals. Proposes only; never mutates state."""

import time
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StringConstraints

from forma_api import diagnosis_runtime
from forma_api.intake_runtime import (
    gateway_error_details as _shared_gateway_error_details,
)
from forma_api.model_gateway import GatewayError, MetaGateway, ProposalBudget
from forma_api.proposal_prompts import instructions
from forma_api.provider_diagnostics import ProviderUsage, summarize_usage
from forma_domain.models import (
    ID,
    BuildPlan,
    DiagnosisProposal,
    Record,
    RepairPatch,
    RepairProposals,
    Stock,
    Text,
)

MAX_REPORTED_PROBLEM_LENGTH = 1000

REPAIR_SYSTEM_PROMPT = instructions("repair")

REPAIR_PROMPT = (
    "Propose at most three typed repair patches using only the supplied "
    "saved context, or ask targeted questions when facts are missing."
)


class RepairProposeRequest(Record):
    expected_version_id: ID
    expected_last_event_id: ID | None
    reported_problem: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_REPORTED_PROBLEM_LENGTH,
        ),
    ]
    diagnosis: DiagnosisProposal
    provider_context_consented: StrictBool = False


class RepairProposeDiagnostics(Record):
    status: Literal["ok"]
    model: str = Field(min_length=1, max_length=80)
    elapsed_ms: int = Field(ge=0)
    usage: ProviderUsage | None = None


class RepairProposeErrorResponse(Record):
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


PROVIDER_ERROR_CODES: frozenset[str] = frozenset(
    {
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
    }
)


class RepairProposeResult(Record):
    project_id: ID
    base_version_id: ID
    base_last_event_id: ID | None
    candidates: tuple[RepairPatch, ...] = Field(max_length=3)
    questions: tuple[Text, ...] = Field(max_length=8)
    diagnostics: RepairProposeDiagnostics


def default_gateway_factory() -> MetaGateway:
    return MetaGateway.from_env()


def _profile_ids(plan: BuildPlan) -> set[str]:
    ids = {profile.id for profile in plan.joint_profiles}
    ids.update(joint.profile_id for joint in plan.joints)
    return ids


def build_context(
    *,
    project_id: str,
    project_goal: str,
    reported_problem: str,
    diagnosis: DiagnosisProposal,
    plan: BuildPlan,
    completed_operation_ids: tuple[str, ...] = (),
    failed_operation_ids: tuple[str, ...] = (),
    expected_remaining_stock: tuple[Stock, ...] = (),
) -> dict:
    """Only saved typed facts; user report and diagnosis stay flagged."""
    # Reuse the diagnosis active-plan shape without inventory duplication.
    active_plan = diagnosis_runtime.build_context(
        project_id=project_id,
        revision_id=plan.version_id,
        project_goal=project_goal,
        reported_problem=reported_problem,
        stocks=(),
        plan=plan,
    )["active_plan"]
    part_ids = sorted(part.id for part in plan.parts)
    joint_ids = sorted(joint.id for joint in plan.joints)
    profile_ids = sorted(_profile_ids(plan))
    stock_ids = sorted(stock.id for stock in expected_remaining_stock)
    return {
        "project_id": project_id,
        "project_goal": project_goal,
        "reported_problem": reported_problem,
        "reported_problem_is_observed_fact": False,
        "diagnosis": diagnosis.model_dump(mode="json"),
        "diagnosis_is_unverified_model_output": True,
        "active_plan": active_plan,
        "completed_operation_ids": list(completed_operation_ids),
        "failed_operation_ids": list(failed_operation_ids),
        "expected_remaining_stock": [
            stock.model_dump(mode="json") for stock in expected_remaining_stock
        ],
        "joint_profile_ids": profile_ids,
        "allowed_ids": {
            "base_version_id": plan.version_id,
            "resize_part": part_ids,
            "replace_part": part_ids,
            "replace_joint_profile": joint_ids,
            "change_angle": [plan.version_id],
            "replacement_stock_ids": stock_ids,
            "replacement_profile_ids": profile_ids,
        },
    }


def validate_repairs(
    proposals: RepairProposals,
    *,
    plan: BuildPlan,
    expected_remaining_stock: tuple[Stock, ...] = (),
) -> RepairProposals:
    candidates = proposals.candidates
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise GatewayError("invalid_repair_reference")
    # Exact duplicates ignoring only the id are still duplicates in effect.
    effect_keys = [
        candidate.model_dump_json(exclude={"id"}) for candidate in candidates
    ]
    if len(set(effect_keys)) != len(effect_keys):
        raise GatewayError("invalid_repair_reference")
    part_ids = {part.id for part in plan.parts}
    joint_ids = {joint.id for joint in plan.joints}
    profile_ids = _profile_ids(plan)
    stock_ids = {stock.id for stock in expected_remaining_stock}
    for candidate in candidates:
        if candidate.base_version_id != plan.version_id:
            raise GatewayError("invalid_repair_reference")
        if candidate.kind in ("resize_part", "replace_part"):
            if candidate.target_id not in part_ids:
                raise GatewayError("invalid_repair_reference")
        elif candidate.kind == "replace_joint_profile":
            if candidate.target_id not in joint_ids:
                raise GatewayError("invalid_repair_reference")
            if candidate.replacement_profile_id not in profile_ids:
                raise GatewayError("invalid_repair_reference")
        elif candidate.kind == "change_angle":
            if candidate.target_id != plan.version_id:
                raise GatewayError("invalid_repair_reference")
        if (
            candidate.replacement_stock_id is not None
            and candidate.replacement_stock_id not in stock_ids
        ):
            raise GatewayError("invalid_repair_reference")
    if not candidates and not any(q.strip() for q in proposals.questions):
        raise GatewayError("invalid_repair_empty")
    return proposals


def propose_repairs(
    gateway: MetaGateway,
    *,
    context: dict,
    plan: BuildPlan,
    expected_remaining_stock: tuple[Stock, ...] = (),
) -> tuple[RepairProposals, RepairProposeDiagnostics]:
    """Exactly one bounded Muse call; no image, no tool, no retries."""
    start = time.monotonic()
    budget = ProposalBudget(
        max_rounds=getattr(gateway, "max_rounds", 4),
        seconds=getattr(gateway, "budget", 60),
    )
    proposals = gateway.propose(
        REPAIR_PROMPT,
        RepairProposals,
        request_budget=budget,
        system_prompt=REPAIR_SYSTEM_PROMPT,
        context=context,
    )
    validate_repairs(
        proposals, plan=plan, expected_remaining_stock=expected_remaining_stock
    )
    elapsed_ms = round((time.monotonic() - start) * 1000)
    if budget.traces:
        elapsed_ms = budget.traces[-1].elapsed_ms
    model = str(getattr(gateway, "spark", "unknown"))[:80] or "unknown"
    return proposals, RepairProposeDiagnostics(
        status="ok",
        model=model,
        elapsed_ms=elapsed_ms,
        usage=summarize_usage(budget.traces),
    )


def gateway_error_details(code: str) -> tuple[int, str, str]:
    if code in {"invalid_repair_reference", "invalid_repair_empty"}:
        return (
            502,
            "invalid_response",
            "Model provider returned an unusable response; retry",
        )
    return _shared_gateway_error_details(code)
