"""SYNTHETIC attached-base tape undo; no physical build or recovery was performed."""

import pytest
from forma_renderer import render_manual, stand_continuation_blockers
from test_stand_continuation import _attached_brace_replacement, build

BASE = "stand-base"


def replace_base(**kwargs):
    base, snapshot, result, process = _attached_brace_replacement(
        target_id=BASE, **kwargs
    )
    return base, snapshot, result, process


def new_part_id(base, result):
    (new_id,) = {p.id for p in result.plan.parts} - {p.id for p in base.parts}
    return new_id


def test_attached_base_peels_front_and_rear_and_keeps_the_apex():
    base, snapshot, result, process = replace_base()
    assert result.status == "feasible", result.blockers
    assert stand_continuation_blockers(result.plan) == ()
    assert result.cost.known_weighted_cost == 8
    assert result.cost.required_physical_undos == 2
    plan = result.plan
    new_id = new_part_id(base, result)
    tape_id = next(s.id for s in base.stocks if s.kind == "tape")

    peels = [o for o in plan.operations if o.type == "detach"]
    assert [o.args.joint_id for o in peels] == [
        "stand-joint-front",
        "stand-joint-rear",
    ]
    assert tuple(result.required_undo_operation_ids) == tuple(o.id for o in peels)
    # Hinge-specific partner checks: the support for the front, the brace for the rear.
    for peel, partner in zip(peels, ("stand-support", "stand-brace"), strict=True):
        assert peel.args.supported_inverse == "peel_tape"
        assert peel.args.material_loss_stock_ids == (tape_id,)
        assert partner in peel.preconditions.accessible_part_ids
        checks = " ".join(peel.preconditions.human_checks)
        assert f"undamaged partner part {partner}" in checks
    # The apex stays attached and is preserved; the original joins stay in history.
    assert plan.operations[:6] == base.operations[:6]
    assert "stand-joint-apex-attach" in result.preserved_operation_ids
    assert set(result.lost_operation_ids) == {
        "stand-joint-front-attach",
        "stand-joint-rear-attach",
    }
    assert result.lost_part_ids == (BASE,)

    # New, incomplete attachments keep each joint's original part order.
    new_joints = {
        j.id: j.part_ids for j in plan.joints if j.id not in {j.id for j in base.joints}
    }
    assert sorted(new_joints.values()) == sorted(
        [("stand-support", new_id), (new_id, "stand-brace")]
    )
    reattach = [
        o for o in plan.operations if getattr(o.args, "joint_id", None) in new_joints
    ]
    assert [o.type for o in reattach] == ["tape_joint", "tape_joint"]
    assert all(o.id in result.incomplete_operation_ids for o in [*peels, *reattach])
    test = plan.operations[-1]
    assert test.preconditions.required_joint_ids == (
        *(j for j in new_joints if j.startswith("stand-joint-front")),
        *(j for j in new_joints if j.startswith("stand-joint-rear")),
        "stand-joint-apex",
    )
    # No events are recorded by simulation.
    assert all(
        e.operation_id not in result.incomplete_operation_ids for e in snapshot.events
    )


def test_attached_base_spends_new_tape_only_and_reconciles_the_rest():
    base, _snapshot, result, process = replace_base()
    peels = set(result.required_undo_operation_ids)
    tape = [d for d in result.proposed_material_deltas if d.unit == "mm"]
    # Peeled tape is lost, never refunded: only the two new joins consume tape.
    assert [(d.kind, d.quantity) for d in tape] == [("consume", 80.0)] * 2
    assert all(d.operation_id not in peels for d in result.proposed_material_deltas)
    _plan, parameters, _p = build()
    rendered = render_manual(
        result.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert rendered.status == "accepted", rendered.blockers
    assert len(rendered.panels) == 14
    # From the reattachments on, panels draw the replacement, never the retired base.
    new_id = new_part_id(base, result)
    for panel in rendered.panels[10:]:
        assert new_id in panel.part_ids and BASE not in panel.part_ids
        assert new_id in panel.svg and BASE not in panel.svg
    retired = next(i for i in rendered.bill_of_materials if i.id == BASE)
    assert retired.quantity == 0 and new_id in retired.description
    tape_id = next(s.id for s in base.stocks if s.kind == "tape")
    remaining = next(
        item for item in rendered.bill_of_materials if item.id == f"{tape_id}-remaining"
    )
    # 500 - 240 historical - 160 reattachment = 100.
    assert remaining.quantity == 100


@pytest.mark.parametrize(("completed", "panels"), [(7, 15), (8, 16)])
def test_attached_base_after_final_checks_adds_fresh_checks(completed, panels):
    base, _snapshot, result, process = replace_base(completed_count=completed)
    assert result.status == "feasible", result.blockers
    assert stand_continuation_blockers(result.plan) == ()
    _plan, parameters, _p = build()
    rendered = render_manual(
        result.plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert rendered.status == "accepted", rendered.blockers
    assert len(rendered.panels) == panels


def test_attached_base_needs_every_join_done_and_enough_tape():
    _base, _snapshot, partial, _process = replace_base(completed_count=5)
    # With the apex unattached this is not the attached-base case; the generic
    # path refuses to replace a part held by completed joins.
    assert partial.status == "blocked"
    _base, _snapshot, short, _process = replace_base(tape_length=399)
    assert short.status == "blocked"
    assert any(b.code == "stock_exhausted" for b in short.blockers)


def test_attached_base_irreversible_front_tape_blocks():
    def mutate(plan):
        return plan.model_copy(
            update={
                "operations": tuple(
                    o.model_copy(update={"reversible": "irreversible"})
                    if o.id == "stand-joint-front-attach"
                    else o
                    for o in plan.operations
                )
            }
        )

    _base, _snapshot, result, _process = replace_base(mutate_plan=mutate)
    assert result.status == "blocked"
    assert any(
        b.code == "irreversible_conflict"
        and b.target_ids == ("stand-joint-front-attach",)
        for b in result.blockers
    )


def test_missing_historical_part_is_a_blocker_not_a_crash():
    _base, _snapshot, result, _process = replace_base()
    without_base = result.plan.model_copy(
        update={"parts": tuple(p for p in result.plan.parts if p.id != BASE)}
    )
    (blocker,) = stand_continuation_blockers(without_base)
    assert blocker.code == "invalid_reference"
    assert blocker.target_ids == (BASE,)
