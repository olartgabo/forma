"""Bounded repair search contracts.

A search enumerates repairs from the operators FORMA already supports, checks
each with the existing simulator and fabrication rules, and ranks feasible
ones by known terms. It proposes; only explicit approval commits a revision,
and neither search nor selection records physical work.
"""

from typing import Literal

from pydantic import Field

from forma_domain.models import ID, Blocker, Positive, Record, RepairPatch

REPAIR_SEARCH_VERSION = "repair-search-v1"

# Every candidate is simulated in full, so the bound is on evaluations.
MAX_EVALUATED = 12


class ResizeMeasurement(Record):
    """A user-measured size a resize candidate may target; never inferred."""

    part_id: ID
    width_mm: Positive
    height_mm: Positive
    user_confirmed: Literal[True]


class RepairSearchLimits(Record):
    max_evaluated: int = Field(ge=1, le=MAX_EVALUATED)
    max_results: int = Field(ge=1, le=3)


class CandidateOutcome(Record):
    patch: RepairPatch
    status: Literal["ranked", "infeasible", "cycle", "duplicate", "not_evaluated"]
    rank: int | None
    preview_id: ID | None
    blockers: tuple[Blocker, ...]


class RepairSearchSummary(Record):
    """``exhausted`` means the evaluation limit stopped the search before every
    generated candidate was checked; ``infeasible`` means all were checked."""

    search_version: Literal["repair-search-v1"]
    status: Literal["found", "infeasible", "exhausted"]
    target_ids: tuple[ID, ...]
    generated_count: int = Field(ge=0)
    evaluated_count: int = Field(ge=0)
    limits: RepairSearchLimits
    outcomes: tuple[CandidateOutcome, ...]
    unknown_cost_terms: tuple[Literal["time", "purchase_price", "strength"], ...]
    stability_coverage: Literal["unverified"]
