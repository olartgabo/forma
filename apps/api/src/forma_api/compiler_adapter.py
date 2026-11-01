"""Trusted server-side adapter from proposal candidates to offline validators."""

from datetime import datetime

from forma_compiler import CutProcess
from forma_renderer import StandParameters, compile_stand, stand_continuation_blockers
from forma_renderer.template import profile_evidence_valid
from forma_replanner import SimulationResult, simulate_patch

from forma_api.proposal_service import CandidateFeedback, ProposalSnapshot, Validator
from forma_domain import models as m


def _needs_measurement(message: str) -> CandidateFeedback:
    return CandidateFeedback(
        status="needs_measurement",
        blockers=(m.Blocker(code="missing_measurement", message=message),),
    )


def _blocked(code: str, message: str) -> CandidateFeedback:
    return CandidateFeedback(
        status="blocked",
        blockers=(m.Blocker(code=code, message=message),),
    )


def build_validator(
    *,
    process: CutProcess | None = None,
    stand_parameters: StandParameters | None = None,
    profile_evidence: tuple[m.Evidence, ...] = (),
    base_plan: m.BuildPlan | None = None,
    events: tuple[m.PhysicalEvent, ...] = (),
    evidence: tuple[m.Evidence, ...] = (),
    material_transactions: tuple[m.MaterialTransaction, ...] = (),
    historical_plans: tuple[m.BuildPlan, ...] = (),
    created_at: datetime | None = None,
    allow_synthetic: bool = False,
) -> Validator:
    trusted_profile_evidence = tuple(profile_evidence)
    trusted_events = tuple(events)
    trusted_evidence = tuple(evidence)
    trusted_transactions = tuple(material_transactions)
    trusted_history = tuple(historical_plans)
    trusted_base = base_plan
    trusted_created_at = created_at

    def validate(
        candidate: m.DesignCandidate | m.RepairPatch,
        snapshot: ProposalSnapshot,
    ) -> m.CompilerResult | CandidateFeedback | SimulationResult:
        if isinstance(candidate, m.DesignCandidate):
            if process is None:
                return _needs_measurement(
                    "Missing trusted cutting process: provide a measured "
                    "cutting process before compiling a design."
                )
            if stand_parameters is None:
                return _needs_measurement(
                    "Missing trusted stand parameters: provide measured "
                    "stand parameters before compiling a design."
                )
            if trusted_created_at is None:
                return _needs_measurement(
                    "Missing trusted creation time: provide a server-side "
                    "creation time before compiling a design."
                )
            compiler_input = m.CompilerInput(
                project_id=snapshot.project_id,
                version_id=snapshot.version_id,
                created_at=trusted_created_at,
                candidate=candidate,
                stocks=snapshot.stocks,
                joint_profiles=snapshot.profiles,
                constraints=snapshot.constraints,
                kerf_mm=process.kerf_min_mm,
                edge_margin_mm=process.edge_margin_min_mm,
                process_evidence_ids=tuple(e.id for e in process.evidence),
            )
            parameters = StandParameters.model_validate(
                stand_parameters.model_dump(mode="python")
                | {"profile_evidence": trusted_profile_evidence}
            )
            return compile_stand(
                compiler_input,
                parameters,
                process=process,
                allow_synthetic=allow_synthetic,
            )

        if isinstance(candidate, m.RepairPatch):
            if trusted_base is None:
                return _needs_measurement(
                    "Missing trusted base plan: provide the bound base plan "
                    "before simulating a repair."
                )
            if process is None:
                return _needs_measurement(
                    "Missing trusted cutting process: provide a measured "
                    "cutting process before simulating a repair."
                )
            if snapshot.project_id != trusted_base.project_id:
                return _blocked(
                    "invalid_reference",
                    "Snapshot project does not match the trusted base plan.",
                )
            if snapshot.version_id != trusted_base.version_id:
                return _blocked(
                    "stale_version",
                    "Snapshot version does not match the trusted base plan version.",
                )
            if candidate.base_version_id != trusted_base.version_id:
                return _blocked(
                    "stale_version",
                    "Repair patch does not match the trusted base plan version.",
                )
            if (
                snapshot.plan != trusted_base
                or snapshot.constraints != trusted_base.constraints
            ):
                return _blocked(
                    "invalid_reference",
                    "Snapshot plan or constraints do not match the trusted base plan.",
                )
            if (
                snapshot.events != trusted_events
                or snapshot.evidence != trusted_evidence
            ):
                return _blocked(
                    "invalid_reference",
                    "Snapshot events or evidence do not match the trusted history.",
                )
            if snapshot.profiles != trusted_base.joint_profiles:
                return _blocked(
                    "invalid_reference",
                    "Snapshot profiles do not match the trusted base plan profiles.",
                )
            history_evidence = {item.id: item for item in trusted_evidence}
            if any(
                history_evidence.get(item.id) != item
                for item in trusted_profile_evidence
            ):
                return _blocked(
                    "invalid_reference",
                    "Trusted profile evidence conflicts with the bound history.",
                )
            if not profile_evidence_valid(
                trusted_base.joint_profiles,
                trusted_profile_evidence,
                trusted_base.project_id,
                allow_synthetic=allow_synthetic,
            ):
                return _blocked(
                    "unsupported_profile",
                    "Resolve measured profile evidence before simulating a repair.",
                )
            replanner_input = m.ReplannerInput(
                base_plan=trusted_base,
                events=trusted_events,
                evidence=trusted_evidence,
                material_transactions=trusted_transactions,
                remaining_stock=snapshot.stocks,
                patch=candidate,
            )
            return simulate_patch(
                replanner_input,
                process=process,
                allow_synthetic=allow_synthetic,
                historical_plans=trusted_history,
                family_validator=stand_continuation_blockers,
            )

        raise TypeError(f"Unsupported candidate type: {type(candidate).__name__}")

    return validate
