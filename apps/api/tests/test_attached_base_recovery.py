"""Synthetic attached-base recovery through the API; no physical attempt or pass."""

import test_adapt
from test_adapt import (
    active,
    commit,
    joined,
    patch,
    progress,
    report,
    report_damage,
    simulate,
)

from forma_domain.models import BuildPlan

setup = test_adapt.setup


def test_damaged_attached_base_recovers_through_reviewed_approval(setup):
    client, version, _ = setup
    plan = version.plan
    damaged = report_damage(
        client, plan, joined(client, version), part_ids=["stand-base"]
    )
    response = simulate(
        client, plan, damaged, [patch(plan, "replace-base", target_id="stand-base")]
    )
    assert response.status_code == 200, response.text
    preview = response.json()["previews"][0]
    simulation = preview["simulation"]
    assert simulation["status"] == "feasible", simulation["blockers"]
    assert simulation["lost_part_ids"] == ["stand-base"]
    assert set(simulation["lost_operation_ids"]) == {
        "stand-joint-front-attach",
        "stand-joint-rear-attach",
    }
    assert "stand-joint-apex-attach" in simulation["preserved_operation_ids"]
    tape = [d for d in simulation["proposed_material_deltas"] if d["unit"] == "mm"]
    assert [(d["kind"], d["quantity"]) for d in tape] == [("consume", 80.0)] * 2
    assert preview["version"]["manual"]["physical_verification"] == "not_attempted"
    assert active(client, plan.project_id) == plan.version_id

    approved = commit(client, plan, damaged, preview["preview_id"])
    assert approved.status_code == 200, approved.text
    revision = approved.json()["revision"]
    assert revision["carried_completed_operation_ids"] == [
        op.id for op in plan.operations[:6]
    ]
    # The base version keeps its damage report; the revision starts clean.
    assert progress(client, plan.project_id, plan.version_id) == damaged
    revised = BuildPlan.model_validate(preview["version"]["plan"])
    front_peel = simulation["required_undo_operation_ids"][0]
    after = report(client, plan.project_id, revised, front_peel)
    assert front_peel in after["completed_operation_ids"]
    assert after["status"] == "building"
