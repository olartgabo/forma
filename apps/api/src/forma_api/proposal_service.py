"""Bounded proposal orchestration. No routes, writes, manual mutation or approval."""

import json
import time
from dataclasses import asdict
from typing import Callable, Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from forma_api.model_gateway import (
    GatewayError,
    ImageInput,
    MetaGateway,
    ProposalBudget,
    Tool,
)
from forma_api.proposal_prompts import PROMPT_VERSION, SCHEMA_VERSION, instructions
from forma_domain.models import (
    ID,
    Blocker,
    BuildPlan,
    CompilerResult,
    Constraints,
    DesignCandidate,
    DesignProposals,
    DiagnosisProposal,
    Evidence,
    JointProfile,
    PhysicalEvent,
    Record,
    RepairPatch,
    RepairProposals,
    Stock,
    Text,
    unique,
)

Task = Literal["intake", "design", "diagnose", "repair"]


class HistoricalScope(Record):
    """IDs resolved from one authorized immutable historical plan, never model input."""

    version_id: ID
    operation_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    part_ids: tuple[ID, ...] = Field(default=(), max_length=128)
    checkpoint_ids: tuple[ID, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def distinct(self):
        for ids in (self.operation_ids, self.part_ids, self.checkpoint_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate historical scope ID")
        return self


class ProposalSnapshot(Record):
    """Caller authenticates scope and resolves historical IDs before creating this view."""

    project_id: ID
    version_id: ID
    historical_scopes: tuple[HistoricalScope, ...] = Field(default=(), max_length=16)
    stocks: tuple[Stock, ...] = Field(max_length=32)
    profiles: tuple[JointProfile, ...] = Field(max_length=32)
    constraints: Constraints
    plan: BuildPlan | None = None
    events: tuple[PhysicalEvent, ...] = Field(default=(), max_length=128)
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=128)
    current_operation_id: ID | None = None

    @model_validator(mode="after")
    def scope(self):
        for values in (self.stocks, self.profiles, self.events, self.evidence):
            unique(values, "snapshot")
        if self.plan and (
            self.plan.project_id != self.project_id
            or self.plan.version_id != self.version_id
            or self.plan.constraints != self.constraints
        ):
            raise ValueError("snapshot plan scope/constraints mismatch")
        if self.plan and any(
            len(getattr(self.plan, field)) > 128
            for field in ("parts", "joints", "operations", "checkpoints")
        ):
            raise ValueError("plan snapshot too large")
        operations = {o.id for o in self.plan.operations} if self.plan else set()
        parts = {p.id for p in self.plan.parts} if self.plan else set()
        checkpoints = {c.id for c in self.plan.checkpoints} if self.plan else set()
        if self.current_operation_id and self.current_operation_id not in operations:
            raise ValueError("unknown current operation")
        history = {scope.version_id: scope for scope in self.historical_scopes}
        if len(history) != len(self.historical_scopes) or self.version_id in history:
            raise ValueError("duplicate/current historical scope")
        versions = {self.version_id, *history}
        evidence_ids = {e.id for e in self.evidence}
        for event in self.events:
            allowed_operations = (
                set(history[event.version_id].operation_ids)
                if event.version_id in history
                else operations
            )
            if (
                event.project_id != self.project_id
                or event.version_id not in versions
                or (event.operation_id and event.operation_id not in allowed_operations)
                or not set(event.evidence_ids) <= evidence_ids
            ):
                raise ValueError("event outside snapshot scope")
        if tuple(sorted(self.events, key=lambda e: e.recorded_at)) != self.events:
            raise ValueError("events not chronological")
        for evidence in self.evidence:
            historical = history.get(evidence.version_id)
            allowed_operations = (
                set(historical.operation_ids) if historical else operations
            )
            allowed_parts = set(historical.part_ids) if historical else parts
            allowed_checkpoints = (
                set(historical.checkpoint_ids) if historical else checkpoints
            )
            if (
                evidence.project_id != self.project_id
                or evidence.version_id not in versions
                or not set(evidence.operation_ids) <= allowed_operations
                or not set(evidence.part_ids) <= allowed_parts
                or not set(evidence.checkpoint_ids) <= allowed_checkpoints
            ):
                raise ValueError("evidence outside snapshot scope")
        if not set(self.constraints.allowed_profile_ids) <= {
            p.id for p in self.profiles
        }:
            raise ValueError("unknown allowed profile")
        for profile in self.profiles:
            if not set(profile.test_evidence_ids) <= evidence_ids:
                raise ValueError("unresolved profile evidence")
        for stock in self.stocks:
            for dimension in (
                stock.width_mm,
                stock.height_mm,
                stock.thickness_mm,
                stock.remaining_length_mm,
            ):
                if not set(dimension.evidence_ids) <= evidence_ids:
                    raise ValueError("unresolved measurement evidence")
        return self


class IntakeObservation(Record):
    labels: tuple[Text, ...] = Field(max_length=12)
    measurement_source: Literal["unknown"]
    questions: tuple[Text, ...] = Field(max_length=8)


class ScopedToolArgs(Record):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project_id: ID
    version_id: ID


class ProfileToolArgs(ScopedToolArgs):
    profile_ids: tuple[ID, ...] = Field(max_length=16)


class ProfileToolResult(Record):
    profiles: tuple[JointProfile, ...]


class CandidateFeedback(Record):
    status: Literal["accepted", "blocked", "needs_measurement", "unsupported"]
    blockers: tuple[Blocker, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "accepted") == bool(self.blockers):
            raise ValueError("feedback acceptance and blockers disagree")
        return self


class CandidateReview(Record):
    candidate_id: ID
    feedback: CandidateFeedback


class SafeProposalTrace(Record):
    task: Task
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    elapsed_ms: int
    model_rounds: int
    tool_executions: int
    outcome: str
    error_code: str | None
    transports: tuple[dict, ...]


class ProposalOutcome(Record):
    status: Literal["proposed", "blocked", "needs_clarification", "stopped"]
    proposal: (
        IntakeObservation | DesignProposals | DiagnosisProposal | RepairProposals | None
    ) = None
    reviews: tuple[CandidateReview, ...] = ()
    questions: tuple[Text, ...] = ()
    error_code: str | None = None
    trace: SafeProposalTrace


Validator = Callable[
    [DesignCandidate | RepairPatch, ProposalSnapshot],
    CompilerResult | CandidateFeedback,
]


class ProposalService:
    def __init__(
        self,
        gateway: MetaGateway,
        validator: Validator | None = None,
        *,
        max_rounds: int = 4,
        budget_seconds: float = 60,
    ):
        self.gateway, self.validator = gateway, validator
        # Validate even when no provider request is needed.
        ProposalBudget(max_rounds, budget_seconds)
        self.max_rounds, self.budget_seconds = max_rounds, budget_seconds

    @staticmethod
    def _scope_tool(args: ScopedToolArgs, snapshot: ProposalSnapshot):
        if (
            args.project_id != snapshot.project_id
            or args.version_id != snapshot.version_id
        ):
            raise GatewayError("invalid_tool_scope")

    def run(
        self,
        task: Task,
        snapshot: ProposalSnapshot | dict,
        user_text: str,
        *,
        image: ImageInput | None = None,
        photo_evidence_id: str | None = None,
    ) -> ProposalOutcome:
        start = time.monotonic()
        budget = ProposalBudget(self.max_rounds, self.budget_seconds)
        reviews: list[CandidateReview] = []
        executions = 0

        def finish(status, proposal=None, questions=(), error=None):
            transport_codes = {
                "ok",
                "timeout",
                "budget_exhausted",
                "authentication",
                "access_denied",
                "rate_limit",
                "provider_http_error",
                "invalid_response",
                "response_too_large",
                "network_error",
            }
            transports = tuple(
                asdict(trace)
                | {
                    "status": trace.status
                    if trace.status in transport_codes
                    else "provider_error"
                }
                for trace in budget.traces
            )
            return ProposalOutcome(
                status=status,
                proposal=proposal,
                reviews=tuple(reviews),
                questions=questions,
                error_code=error,
                trace=SafeProposalTrace(
                    task=task,
                    elapsed_ms=round((time.monotonic() - start) * 1000),
                    model_rounds=budget.rounds,
                    tool_executions=executions,
                    outcome=status,
                    error_code=error,
                    transports=transports,
                ),
            )

        if task not in ("intake", "design", "diagnose", "repair"):
            raise ValueError("unknown proposal task")
        try:
            raw = (
                snapshot.model_dump_json()
                if isinstance(snapshot, ProposalSnapshot)
                else json.dumps(snapshot)
            )
            snapshot = ProposalSnapshot.model_validate_json(raw, strict=True)
            if len(raw) > 48000:
                raise GatewayError("context_too_large")
            if not isinstance(user_text, str) or not 0 < len(user_text) <= 4000:
                raise GatewayError("invalid_prompt")
            if task in ("repair", "diagnose") and not snapshot.plan:
                return finish(
                    "needs_clarification",
                    questions=("Provide the current validated plan and step.",),
                )
            if task == "diagnose" and not snapshot.current_operation_id:
                return finish(
                    "needs_clarification",
                    questions=("Which current operation failed?",),
                )
            if image:
                photo = next(
                    (e for e in snapshot.evidence if e.id == photo_evidence_id), None
                )
                if (
                    not photo
                    or photo.kind != "photo"
                    or photo.provenance != "user"
                    or not photo.asset_id
                    or photo.verification_state == "invalidated"
                ):
                    raise GatewayError("invalid_photo_scope")
                image.data_url()  # Validate consent and local input before any call.
            elif photo_evidence_id:
                raise GatewayError("photo_bytes_missing")
            if task == "diagnose" and image is None:
                return finish(
                    "needs_clarification",
                    questions=("Provide a consented photo of the current step.",),
                )
            if task in ("design", "repair") and self.validator is None:
                return finish("stopped", error="compiler_unavailable")

            def get_snapshot(args):
                nonlocal executions
                budget.check()
                self._scope_tool(args, snapshot)
                executions += 1
                return snapshot

            def get_profiles(args):
                nonlocal executions
                budget.check()
                self._scope_tool(args, snapshot)
                profiles = {p.id: p for p in snapshot.profiles}
                if (
                    len(set(args.profile_ids)) != len(args.profile_ids)
                    or not set(args.profile_ids) <= profiles.keys()
                ):
                    raise GatewayError("invalid_profile_reference")
                executions += 1
                return ProfileToolResult(
                    profiles=tuple(profiles[id] for id in args.profile_ids)
                )

            tool = (
                Tool(
                    "get_supported_joint_profiles",
                    ProfileToolArgs,
                    ProfileToolResult,
                    get_profiles,
                )
                if task in ("design", "repair")
                else Tool(
                    "get_project_snapshot",
                    ScopedToolArgs,
                    ProposalSnapshot,
                    get_snapshot,
                )
            )
            schema = {
                "intake": IntakeObservation,
                "design": DesignProposals,
                "diagnose": DiagnosisProposal,
                "repair": RepairProposals,
            }[task]
            context = {
                "snapshot": snapshot.model_dump(mode="json"),
                "compiler_feedback": [],
                "remaining_candidates": 2 if task == "design" else 3,
            }
            attempted = 0
            seen_ids = set()
            while True:
                proposal = self.gateway.propose(
                    user_text,
                    schema,
                    image=image,
                    tool=tool,
                    request_budget=budget,
                    system_prompt=instructions(task),
                    context=context,
                )
                budget.check()
                if isinstance(proposal, IntakeObservation):
                    return finish(
                        "needs_clarification" if proposal.questions else "proposed",
                        proposal,
                        proposal.questions,
                    )
                if isinstance(proposal, DiagnosisProposal):
                    allowed = self._target_ids(snapshot)
                    if not set(proposal.affected_ids) <= allowed:
                        raise GatewayError("invalid_diagnosis_reference")
                    return finish(
                        "needs_clarification"
                        if proposal.questions_or_measurements
                        else "proposed",
                        proposal,
                        proposal.questions_or_measurements,
                    )
                cap = 2 if task == "design" else 3
                if attempted + len(proposal.candidates) > cap:
                    raise GatewayError("candidate_limit")
                accepted = []
                for candidate in proposal.candidates:
                    budget.check()
                    if candidate.id in seen_ids:
                        raise GatewayError("duplicate_candidate")
                    seen_ids.add(candidate.id)
                    attempted += 1
                    blockers = self._references(candidate, snapshot)
                    if blockers:
                        feedback = CandidateFeedback(
                            status="blocked", blockers=blockers
                        )
                    else:
                        try:
                            checked = self.validator(candidate, snapshot)
                            if isinstance(checked, CompilerResult):
                                checked = CompilerResult.model_validate_json(
                                    checked.model_dump_json(), strict=True
                                )
                                if (
                                    checked.plan
                                    and checked.plan.project_id != snapshot.project_id
                                ):
                                    raise ValueError("compiler plan project mismatch")
                                feedback = CandidateFeedback(
                                    status=checked.status, blockers=checked.blockers
                                )
                            elif isinstance(checked, CandidateFeedback):
                                feedback = CandidateFeedback.model_validate_json(
                                    checked.model_dump_json(), strict=True
                                )
                            else:
                                raise ValueError(
                                    "compiler callback must return typed feedback"
                                )
                        except Exception:
                            raise GatewayError("compiler_failed") from None
                    budget.check()
                    reviews.append(
                        CandidateReview(candidate_id=candidate.id, feedback=feedback)
                    )
                    if feedback.status == "accepted":
                        accepted.append(candidate)
                if accepted:
                    # Never return rejected candidates as the usable proposal.
                    filtered = schema(
                        candidates=tuple(accepted), questions=proposal.questions
                    )
                    return finish("proposed", filtered, proposal.questions)
                if proposal.questions:
                    return finish("needs_clarification", questions=proposal.questions)
                if not proposal.candidates or attempted >= cap:
                    return finish(
                        "blocked",
                        questions=(
                            "Resolve the listed compiler blockers or provide a measurement.",
                        ),
                    )
                context["compiler_feedback"] = [
                    review.model_dump(mode="json") for review in reviews
                ]
                context["remaining_candidates"] = cap - attempted
                # Retry with exact feedback and the same absolute budget/round counter.
        except ValidationError:
            return finish("stopped", error="invalid_snapshot")
        except (TypeError, ValueError):
            return finish("stopped", error="invalid_snapshot")
        except GatewayError as exc:
            safe = (
                exc.code
                if exc.code
                in {
                    "timeout",
                    "budget_exhausted",
                    "round_limit",
                    "rate_limit",
                    "authentication",
                    "access_denied",
                    "provider_http_error",
                    "network_error",
                    "invalid_response",
                    "response_too_large",
                    "refusal",
                    "invalid_proposal",
                    "invalid_tool_call",
                    "tool_failed",
                    "incomplete_output",
                    "context_too_large",
                    "invalid_prompt",
                    "invalid_photo_scope",
                    "photo_bytes_missing",
                    "image_consent_required",
                    "invalid_image",
                    "invalid_diagnosis_reference",
                    "candidate_limit",
                    "duplicate_candidate",
                    "compiler_failed",
                }
                else "proposal_failed"
            )
            questions = (
                (
                    "Provide the missing measurement or a clearer photo before trying again.",
                )
                if safe in ("timeout", "budget_exhausted", "round_limit")
                else ()
            )
            return finish("stopped", questions=questions, error=safe)

    @staticmethod
    def _target_ids(snapshot):
        ids = {snapshot.version_id, *(s.id for s in snapshot.stocks)}
        if snapshot.plan:
            for field in ("parts", "joints", "operations", "checkpoints"):
                ids.update(item.id for item in getattr(snapshot.plan, field))
            ids.update(
                feature.id for part in snapshot.plan.parts for feature in part.features
            )
        for history in snapshot.historical_scopes:
            ids.update(
                history.operation_ids + history.part_ids + history.checkpoint_ids
            )
        return ids

    @staticmethod
    def _references(candidate, snapshot):
        stocks = {s.id for s in snapshot.stocks}
        profiles = {p.id for p in snapshot.profiles}
        allowed_profiles = set(snapshot.constraints.allowed_profile_ids)
        invalid = []
        code = "invalid_reference"
        if isinstance(candidate, DesignCandidate):
            invalid.extend(id for id in candidate.stock_ids if id not in stocks)
            invalid.extend(
                id
                for id in candidate.profile_ids
                if id not in profiles or id not in allowed_profiles
            )
            if len(set(candidate.stock_ids)) != len(candidate.stock_ids) or len(
                set(candidate.profile_ids)
            ) != len(candidate.profile_ids):
                invalid.append(candidate.id)
        else:
            if candidate.base_version_id != snapshot.version_id:
                return (
                    Blocker(
                        code="stale_version",
                        message="Patch base version differs from the snapshot.",
                        target_ids=(candidate.base_version_id,),
                    ),
                )
            parts = {p.id for p in snapshot.plan.parts}
            joints = {j.id for j in snapshot.plan.joints}
            targets = {
                "resize_part": parts,
                "replace_part": parts,
                "replace_joint_profile": joints,
                "change_angle": {snapshot.version_id},
            }
            if candidate.target_id not in targets[candidate.kind]:
                invalid.append(candidate.target_id)
            if (
                candidate.replacement_stock_id
                and candidate.replacement_stock_id not in stocks
            ):
                invalid.append(candidate.replacement_stock_id)
            if candidate.replacement_profile_id and (
                candidate.replacement_profile_id not in profiles
                or candidate.replacement_profile_id not in allowed_profiles
            ):
                invalid.append(candidate.replacement_profile_id)
        if invalid:
            return (
                Blocker(
                    code=code,
                    message="Proposal references unavailable IDs or duplicates a resource reference.",
                    target_ids=tuple(dict.fromkeys(invalid)),
                ),
            )
        return ()
