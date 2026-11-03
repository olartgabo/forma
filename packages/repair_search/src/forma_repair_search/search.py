"""Evaluate bounded candidates and rank the feasible ones by known terms."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from forma_replanner import SimulationResult

from forma_domain.fabrication_contracts import FabricationReport
from forma_domain.models import Blocker, BuildPlan, RepairPatch
from forma_domain.repair_search_contracts import RepairSearchLimits

# Identity fields a revision always changes; the rest is the physical plan.
_IDENTITY = {"version_id", "parent_version_id", "status", "created_at"}


def plan_fingerprint(plan: BuildPlan) -> str:
    body = plan.model_dump(mode="json", exclude=_IDENTITY)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Outcome:
    patch: RepairPatch
    status: str
    blockers: tuple[Blocker, ...] = ()
    simulation: SimulationResult | None = None
    rank: int | None = None


@dataclass(frozen=True)
class SearchResult:
    status: str
    generated_count: int
    evaluated_count: int
    outcomes: tuple[Outcome, ...]


def fabrication_blockers(report: FabricationReport) -> tuple[Blocker, ...]:
    """A revision is usable only if #150 can schedule all of its remaining work."""
    if report.blockers:
        return report.blockers
    if report.order_status != "complete":
        return report.order_blockers
    return ()


def _rank_key(result: SimulationResult):
    deltas = result.proposed_material_deltas
    return (
        result.cost.known_weighted_cost,
        len(result.required_undo_operation_ids),
        -len(result.preserved_operation_ids),
        sum(d.quantity for d in deltas if d.unit == "mm2" and d.kind != "retire_part"),
        sum(d.quantity for d in deltas if d.unit == "mm"),
        len(result.unknown_physical_checks),
        result.patch_id,
    )


def search_repairs(
    candidates: tuple[RepairPatch, ...],
    *,
    limits: RepairSearchLimits,
    simulate: Callable[[RepairPatch], SimulationResult],
    schedule: Callable[[SimulationResult], FabricationReport],
    prior_plans: tuple[BuildPlan, ...],
) -> SearchResult:
    """Simulate at most ``limits.max_evaluated`` candidates in order.

    Rejected candidates keep their exact blockers. A result that recreates the
    base or an ancestor plan is a cycle; one equal to an earlier candidate's
    result is a duplicate. Ranking uses known cost, undo count, preserved work
    and measured material only; ties break on patch ID.
    """
    seen = {plan_fingerprint(plan): None for plan in prior_plans}
    evaluated = candidates[: limits.max_evaluated]
    outcomes: list[Outcome] = []
    feasible: list[SimulationResult] = []
    for patch in evaluated:
        result = simulate(patch)
        if result.status != "feasible":
            outcomes.append(Outcome(patch, "infeasible", result.blockers, result))
            continue
        fingerprint = plan_fingerprint(result.plan)
        if fingerprint in seen:
            earlier = seen[fingerprint]
            outcomes.append(
                Outcome(
                    patch,
                    "cycle" if earlier is None else "duplicate",
                    (
                        Blocker(
                            code="unsupported",
                            message="This repair recreates an earlier plan version."
                            if earlier is None
                            else f"This repair gives the same plan as {earlier}.",
                            target_ids=(patch.id,),
                        ),
                    ),
                    result,
                )
            )
            continue
        seen[fingerprint] = patch.id
        blockers = fabrication_blockers(schedule(result))
        if blockers:
            outcomes.append(Outcome(patch, "infeasible", blockers, result))
            continue
        feasible.append(result)
        outcomes.append(Outcome(patch, "ranked", (), result))
    ranks = {
        result.patch_id: index + 1
        for index, result in enumerate(sorted(feasible, key=_rank_key))
    }
    outcomes = [
        Outcome(o.patch, o.status, o.blockers, o.simulation, ranks.get(o.patch.id))
        for o in outcomes
    ]
    outcomes.extend(
        Outcome(patch, "not_evaluated") for patch in candidates[len(evaluated) :]
    )
    if ranks:
        status = "found"
    elif len(evaluated) < len(candidates):
        status = "exhausted"
    else:
        status = "infeasible"
    return SearchResult(
        status=status,
        generated_count=len(candidates),
        evaluated_count=len(evaluated),
        outcomes=tuple(sorted(outcomes, key=lambda o: (o.rank is None, o.rank or 0))),
    )
