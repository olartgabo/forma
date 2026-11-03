"""SYNTHETIC search bookkeeping with stub simulations; no physical claim."""

import pytest
from forma_repair_search import generate_candidates, plan_fingerprint, search_repairs
from forma_replanner import RepairCost, SimulationResult

from forma_domain import models as m
from forma_domain.fabrication_contracts import FabricationReport
from forma_domain.repair_search_contracts import RepairSearchLimits, ResizeMeasurement


def measured(value):
    return dict(value=value, unit="mm", source="user_ruler", confirmed=True)


def plan(version_id="v1", width=60, parent=None):
    unknown = dict(value=None, unit="mm", source="unknown", confirmed=False)
    sheet = dict(
        kind="sheet",
        material="cardboard",
        width_mm=measured(200),
        height_mm=measured(120),
        thickness_mm=measured(3),
        remaining_length_mm=unknown,
        condition="usable",
    )
    return m.BuildPlan.model_validate(
        dict(
            project_id="project",
            version_id=version_id,
            parent_version_id=parent,
            status="active",
            stocks=[
                dict(
                    sheet,
                    id="sheet",
                    usable_regions=[
                        dict(id="root", geometry=dict(x=0, y=0, width=200, height=120))
                    ],
                ),
                dict(
                    sheet,
                    id="spare",
                    usable_regions=[
                        dict(
                            id="spare-root",
                            geometry=dict(x=0, y=0, width=200, height=120),
                        )
                    ],
                ),
                dict(sheet, id="used", usable_regions=[]),
            ],
            parts=[
                dict(
                    id="base",
                    source_stock_id="sheet",
                    source_region_id="root",
                    geometry=dict(x=5, y=5, width=width, height=90),
                    condition="usable",
                )
            ],
            joint_profiles=[],
            joints=[],
            operations=[
                dict(
                    id="cut",
                    type="cut_rect",
                    expected_state_id="state",
                    preconditions=dict(safe_tools_confirmed=True),
                    effects=dict(
                        created_part_ids=["base"], consumed_region_ids=["root"]
                    ),
                    args=dict(
                        stock_id="sheet",
                        source_region_id="root",
                        child_part_ids=["base"],
                        kerf_mm=2,
                        edge_margin_mm=5,
                    ),
                )
            ],
            checkpoints=[],
            constraints=dict(
                device_mass_g=dict(
                    value=None, unit="g", source="unknown", confirmed=False
                ),
                support_angle_deg=dict(
                    value=None, unit="deg", source="unknown", confirmed=False
                ),
                max_footprint_width_mm=measured(200),
                max_footprint_height_mm=measured(200),
            ),
            compiler_version="synthetic",
            created_at="2026-10-30T00:00:00Z",
        )
    )


BASE = plan()
LIMITS = RepairSearchLimits(max_evaluated=12, max_results=3)


def patch(patch_id):
    return m.RepairPatch(
        id=patch_id,
        base_version_id="v1",
        kind="replace_part",
        target_id="base",
        replacement_stock_id="spare",
        replacement_profile_id=None,
        width_mm=None,
        height_mm=None,
        angle_deg=None,
        rationale="SYNTHETIC",
    )


def feasible(patch_id, width, cost=3, preserved=(), undo=()):
    return SimulationResult(
        patch_id=patch_id,
        base_version_id="v1",
        status="feasible",
        plan=plan(f"revision-{patch_id}", width=width, parent="v1"),
        preserved_operation_ids=preserved,
        required_undo_operation_ids=undo,
        cost=RepairCost(
            irreversible_completed_actions_lost=0,
            required_physical_undos=len(undo),
            new_irreversible_actions=1,
            known_weighted_cost=cost,
        ),
    )


def blocked(patch_id):
    return SimulationResult(
        patch_id=patch_id,
        base_version_id="v1",
        status="blocked",
        blockers=(m.Blocker(code="unsupported", message="SYNTHETIC unsupported"),),
    )


class Schedule:
    def __init__(self, blockers=None):
        self.blockers = blockers or {}

    def __call__(self, result):
        return FabricationReport.model_construct(
            blockers=self.blockers.get(result.patch_id, ()),
            order_status="complete",
            order_blockers=(),
        )


def run(results, *, limits=LIMITS, schedule=None, prior=(BASE,)):
    by_id = {r.patch_id: r for r in results}
    return search_repairs(
        tuple(patch(r.patch_id) for r in results),
        limits=limits,
        simulate=lambda p: by_id[p.id],
        schedule=schedule or Schedule(),
        prior_plans=prior,
    )


def test_generation_uses_remaining_sheets_and_measured_sizes_only():
    remaining = BASE.stocks
    resize = ResizeMeasurement(
        part_id="base", width_mm=58, height_mm=90, user_confirmed=True
    )
    first = generate_candidates(BASE, ("base",), remaining, (resize,))
    assert [(p.kind, p.replacement_stock_id, p.width_mm) for p in first] == [
        ("replace_part", "sheet", None),
        ("replace_part", "spare", None),
        ("resize_part", None, 58),
    ]
    # "used" has no usable region left, so it is never proposed.
    assert all(p.replacement_stock_id != "used" for p in first)
    assert first == generate_candidates(BASE, ("base", "base"), remaining, (resize,))
    assert generate_candidates(BASE, ("base",), remaining) == first[:2]


def test_ranking_uses_known_terms_and_breaks_ties_by_id():
    result = run(
        (
            feasible("b-cheap", 61, cost=2),
            feasible("a-cheap", 62, cost=2),
            feasible("expensive", 63, cost=8),
            feasible("keeps-more", 64, cost=2, preserved=("cut",)),
        )
    )
    assert result.status == "found"
    assert [(o.patch.id, o.rank) for o in result.outcomes] == [
        ("keeps-more", 1),
        ("a-cheap", 2),
        ("b-cheap", 3),
        ("expensive", 4),
    ]


def test_cycles_duplicates_and_fabrication_rules_reject_candidates():
    back_to_base = feasible("back", 60)
    same_as_first = feasible("twin", 61)
    unschedulable = feasible("stuck", 70)
    stuck = (m.Blocker(code="invalid_order", message="SYNTHETIC no supported order"),)
    result = run(
        (
            feasible("first", 61),
            back_to_base,
            same_as_first,
            unschedulable,
            blocked("no"),
        ),
        schedule=Schedule({"stuck": stuck}),
    )
    status = {o.patch.id: (o.status, o.rank) for o in result.outcomes}
    assert status == {
        "first": ("ranked", 1),
        "back": ("cycle", None),
        "twin": ("duplicate", None),
        "stuck": ("infeasible", None),
        "no": ("infeasible", None),
    }
    assert next(o for o in result.outcomes if o.patch.id == "stuck").blockers == stuck
    assert plan_fingerprint(back_to_base.plan) == plan_fingerprint(BASE)


@pytest.mark.parametrize(
    ("max_evaluated", "status"), [(1, "exhausted"), (2, "infeasible")]
)
def test_exhausted_is_distinct_from_infeasible(max_evaluated, status):
    result = run(
        (blocked("one"), blocked("two")),
        limits=RepairSearchLimits(max_evaluated=max_evaluated, max_results=3),
    )
    assert result.status == status
    assert result.generated_count == 2
    assert result.evaluated_count == max_evaluated
    assert [o.status for o in result.outcomes].count(
        "not_evaluated"
    ) == 2 - max_evaluated
