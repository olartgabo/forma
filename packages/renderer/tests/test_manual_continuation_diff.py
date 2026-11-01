"""SYNTHETIC continuation previews; no physical build or test performed."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from forma_renderer import (
    ManualDiff,
    diff_manuals,
    render_manual,
    stand_continuation_blockers,
)
from forma_renderer.svg import Manual, Panel
from forma_replanner import simulate_patch
from test_stand_continuation import _replacement
from test_stand_manual import build

from forma_domain import models as m


def render(plan, parameters, process):
    before = deepcopy(plan.model_dump())
    result = render_manual(
        plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )
    assert plan.model_dump() == before
    assert result.physical_verification == "not_attempted"
    for panel in result.panels:
        assert "SYNTHETIC" in panel.svg
        assert (
            panel.dependency_hash
            == sha256(("stand-svg-v1\n" + panel.svg).encode()).hexdigest()
        )
    return result


def diff(old, new):
    before = deepcopy((old, new))
    result = diff_manuals(old, new)
    assert (old, new) == before
    return result


@pytest.mark.parametrize("role", ["stand-brace", "stand-base", "stand-support"])
def test_real_replacement_insertion_keeps_original_cut_aligned(role):
    original, snapshot, _, replacement = _replacement(role)
    assert replacement.status == "feasible", replacement.blockers
    _, parameters, process = build()
    old = render(original, parameters, process)
    new = render(replacement.plan, parameters, process)
    assert old.status == new.status == "accepted"
    assert len(old.panels) == 8 and len(new.panels) == 9
    assert old.panels[0].svg == new.panels[1].svg
    assert old.panels[0].dependency_hash == new.panels[1].dependency_hash
    assert old.panels[0].step_key == new.panels[1].step_key == "core:0:cut_rect"
    assert new.panels[0].step_key == "replacement:" + new.panels[0].operation_id
    assert diff(old, new) == ManualDiff(
        unchanged=(1,), changed=(2, 3, 4, 5, 6, 7, 8), added=(0,), removed=()
    )
    assert all(
        p.step_key == f"core:{i}:{op.type}"
        for i, (p, op) in enumerate(zip(old.panels, original.operations))
    )


def panel(key, hash):
    return Panel(
        operation_id="synthetic-op",
        part_ids=(),
        checkpoint_ids=(),
        dependency_hash=hash,
        svg="SYNTHETIC test panel",
        tools=(),
        step_key=key,
    )


def manual(*panels):
    return Manual(status="accepted", panels=panels, bill_of_materials=(), blockers=())


def test_keyed_permutation_uses_new_indices_and_removal_uses_old_indices():
    old = manual(
        panel("core:0:cut_rect", "cut"),
        panel("core:1:inspect", "inspect"),
        panel("core:2:fold", "fold"),
        panel("core:3:tape_joint", "join"),
    )
    new = manual(
        panel("core:2:fold", "fold"),
        panel("replacement:synthetic-cut", "new"),
        panel("core:0:cut_rect", "changed-cut"),
    )
    assert diff(old, new) == ManualDiff(
        unchanged=(0,), changed=(2,), added=(1,), removed=(1, 3)
    )


def test_step_key_metadata_does_not_change_visible_svg_hash():
    plan, parameters, process = build()
    original = render(plan, parameters, process)
    altered = replace(
        original,
        panels=tuple(
            replace(p, step_key="replacement:metadata-only-" + str(i))
            for i, p in enumerate(original.panels)
        ),
    )
    assert [p.svg for p in altered.panels] == [p.svg for p in original.panels]
    assert [p.dependency_hash for p in altered.panels] == [
        p.dependency_hash for p in original.panels
    ]
    assert diff(original, altered) == ManualDiff(
        unchanged=(), changed=(), added=tuple(range(8)), removed=tuple(range(8))
    )


@pytest.mark.parametrize(
    "invalid", ["partial_old", "partial_new", "duplicate_old", "duplicate_new", "mixed"]
)
def test_ambiguous_or_mixed_step_keys_are_rejected(invalid):
    old = manual(panel("core:0:cut_rect", "one"), panel("core:1:inspect", "two"))
    new = old
    if invalid == "partial_old":
        old = replace(
            old, panels=(old.panels[0], replace(old.panels[1], step_key=None))
        )
    elif invalid == "partial_new":
        new = replace(
            new, panels=(new.panels[0], replace(new.panels[1], step_key=None))
        )
    elif invalid == "duplicate_old":
        old = replace(
            old,
            panels=(
                old.panels[0],
                replace(old.panels[1], step_key=old.panels[0].step_key),
            ),
        )
    elif invalid == "duplicate_new":
        new = replace(
            new,
            panels=(
                new.panels[0],
                replace(new.panels[1], step_key=new.panels[0].step_key),
            ),
        )
    else:
        old = replace(old, panels=tuple(replace(p, step_key=None) for p in old.panels))
    before = deepcopy((old, new))
    with pytest.raises(ValueError):
        diff_manuals(old, new)
    assert (old, new) == before


def test_empty_manual_is_neutral_with_keyed_manual():
    empty = manual()
    full = manual(panel("core:0:cut_rect", "one"), panel("core:1:inspect", "two"))
    assert diff(empty, full) == ManualDiff(
        unchanged=(), changed=(), added=(0, 1), removed=()
    )
    assert diff(full, empty) == ManualDiff(
        unchanged=(), changed=(), added=(), removed=(0, 1)
    )


def simulate(plan, process, candidate):
    request = m.ReplannerInput(
        base_plan=plan,
        patch=candidate,
        events=(),
        evidence=(),
        material_transactions=(),
        remaining_stock=plan.stocks,
    )
    before = deepcopy(request.model_dump())
    result = simulate_patch(
        request,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert request.model_dump() == before
    return result


def test_tape_undo_diff_keeps_historical_panels_and_adds_continuation():
    from test_stand_continuation import _attached_brace_replacement

    _base, _snapshot, result, _process = _attached_brace_replacement()
    assert result.status == "feasible", result.blockers
    _, parameters, process = build()
    old_plan, _p, _pr = build()
    old = render(old_plan, parameters, process)
    new = render(result.plan, parameters, process)
    assert len(old.panels) == 8 and len(new.panels) == 14
    assert [p.svg for p in new.panels[:6]] == [p.svg for p in old.panels[:6]]
    keys = [p.step_key for p in new.panels]
    assert len(keys) == len(set(keys))
    assert all(k.startswith("continuation:") for k in keys[6:12])
    outcome = diff(old, new)
    assert outcome.unchanged == tuple(range(6))
    assert outcome.added == tuple(range(6, 12))
    assert outcome.changed == (12, 13)
    assert outcome.removed == ()


def test_noop_resize_is_blocked_while_identical_visible_manuals_have_zero_diff():
    plan, parameters, process = build()
    base = next(p for p in plan.parts if p.id == "stand-base")
    candidate = m.RepairPatch(
        id="synthetic-noop-resize",
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id=base.id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=base.geometry.width,
        height_mm=base.geometry.height,
        angle_deg=None,
        rationale="SYNTHETIC no-op request",
    )
    result = simulate(plan, process, candidate)
    assert result.status == "blocked" and result.plan is None
    old, new = render(plan, parameters, process), render(plan, parameters, process)
    assert diff(old, new) == ManualDiff(
        unchanged=tuple(range(8)), changed=(), added=(), removed=()
    )


def test_angle_patch_and_missing_role_have_no_executable_manual():
    plan, parameters, process = build()
    angle = m.RepairPatch(
        id="synthetic-angle-edit",
        base_version_id=plan.version_id,
        kind="change_angle",
        target_id=plan.version_id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=None,
        height_mm=None,
        angle_deg=55,
        rationale="SYNTHETIC unsupported angle change",
    )
    result = simulate(plan, process, angle)
    assert result.status == "blocked" and result.plan is None
    assert result.blockers
    malformed = plan.model_copy(
        update={"parts": tuple(p for p in plan.parts if p.id != "stand-brace")}
    )
    rendered = render(malformed, parameters, process)
    assert rendered.status == "blocked" and rendered.panels == () and rendered.blockers
