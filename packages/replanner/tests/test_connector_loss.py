"""SYNTHETIC connector-loss ledgers; no physical work or provider calls."""

from copy import deepcopy
from datetime import timedelta

import pytest
from forma_renderer import stand_continuation_blockers
from forma_replanner import simulate_patch
from test_stand_fixture_cases import build_plan, load_raw

from forma_domain import models as m


def case(quantity=20):
    raw = load_raw("missing_connector.json")
    _, _, process, plan = build_plan(raw)
    values = deepcopy(raw["scenarios"][0]["replanner_input"])
    values["base_plan"] = plan
    request = m.ReplannerInput.model_validate(values)
    tx = request.material_transactions[0].model_copy(update={"quantity": quantity})
    remaining = tuple(
        s.model_copy(
            update={
                "remaining_length_mm": s.remaining_length_mm.model_copy(
                    update={"value": 420 - quantity}
                )
            }
        )
        if s.id == tx.source_stock_id
        else s
        for s in request.remaining_stock
    )
    return request.model_copy(
        update={"material_transactions": (tx,), "remaining_stock": remaining}
    ), process


def run(request, process):
    before = deepcopy(request.model_dump())
    process_before = deepcopy(process.model_dump())
    result = simulate_patch(
        request,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert request.model_dump() == before
    assert process.model_dump() == process_before
    return result


def change_loss(request, **updates):
    tx = request.material_transactions[0].model_copy(update=updates)
    return request.model_copy(update={"material_transactions": (tx,)})


def change_loss_event(request, **updates):
    event_id = request.material_transactions[0].physical_event_id
    return request.model_copy(
        update={
            "events": tuple(
                e.model_copy(update=updates) if e.id == event_id else e
                for e in request.events
            )
        }
    )


def change_loss_evidence(request, **updates):
    event = next(
        e
        for e in request.events
        if e.id == request.material_transactions[0].physical_event_id
    )
    return request.model_copy(
        update={
            "evidence": tuple(
                e.model_copy(update=updates) if e.id in event.evidence_ids else e
                for e in request.evidence
            )
        }
    )


def test_exact_connector_loss_debits_history_once_then_blocks_future_join():
    request, process = case(420)
    result = run(request, process)
    assert result.status == "blocked"
    assert [b.code for b in result.blockers] == ["stock_exhausted", "stock_exhausted"]
    assert (
        "connector" in result.blockers[0].message.lower()
        or "tape" in result.blockers[0].message.lower()
    )
    assert result.lost_region_ids == ()
    assert result.proposed_material_deltas == ()


def test_overloss_beyond_rounding_does_not_create_a_negative_ledger():
    request, process = case(420)
    request = change_loss(request, quantity=420.001)
    result = run(request, process)
    assert any(
        b.code == "stock_exhausted"
        and "exceeds the known remaining length" in b.message
        for b in result.blockers
    )


def test_loss_of_whole_remaining_roll_within_rounding_matches_exact_loss():
    # Split decimal losses such as 10.1 + 10.1 + 399.8 sum to 420 only within
    # float rounding; recording the rest of the roll as lost must not conflict.
    exact_request, process = case(420)
    exact = run(exact_request, process)
    drifted = run(change_loss(exact_request, quantity=420 + 5e-8), process)
    assert [b.code for b in drifted.blockers] == [b.code for b in exact.blockers]
    assert not any(
        "exceeds the known remaining length" in b.message for b in drifted.blockers
    )


def test_confirmed_cord_loss_before_tying_is_accounted_once():
    from test_simulation import STAMP, event, joint_data
    from test_simulation import process as cut_process

    data = joint_data()
    for profile in data["base_plan"]["joint_profiles"]:
        profile["strategy"] = "tie"
    data["base_plan"]["operations"][-1]["type"] = "tie_joint"
    for stock in data["base_plan"]["stocks"]:
        if stock["id"] == "tape":
            stock["kind"] = "cord"
    data["events"].append(event("cut_brace"))
    data["remaining_stock"][0]["usable_regions"] = []
    data["remaining_stock"][-1]["kind"] = "cord"
    data["remaining_stock"][-1]["remaining_length_mm"]["value"] = 80
    data["events"].append(
        event(
            "join",
            id="synthetic-cord-loss",
            kind="observation",
            evidence_ids=["synthetic-cord-report"],
        )
    )
    data["evidence"] = [
        dict(
            id="synthetic-cord-report",
            project_id="project",
            version_id="v1",
            kind="user_report",
            provenance="user",
            recorded_at=STAMP,
            description="SYNTHETIC cord loss report; no physical evidence",
            verification_state="user_confirmed",
        )
    ]
    data["material_transactions"] = [
        dict(
            id="synthetic-cord-waste",
            project_id="project",
            version_id="v1",
            operation_id="join",
            source_stock_id="tape",
            kind="waste",
            quantity=20,
            unit="mm",
            recorded_at=STAMP,
            physical_event_id="synthetic-cord-loss",
        )
    ]
    request = m.ReplannerInput.model_validate(data)
    before = deepcopy(request.model_dump())
    result = simulate_patch(request, process=cut_process(), allow_synthetic=True)
    assert request.model_dump() == before
    assert result.status == "feasible", result.blockers
    assert result.lost_region_ids == ()
    assert (
        sum(
            d.quantity
            for d in result.proposed_material_deltas
            if d.kind == "consume" and d.unit == "mm"
        )
        == 80
    )


@pytest.mark.parametrize("kind", ["waste", "damage"])
def test_partial_connector_loss_leaves_future_consumption_only(kind):
    request, process = case(20)
    request = change_loss(request, kind=kind)
    result = run(request, process)
    assert result.status == "feasible", result.blockers
    assert result.lost_region_ids == ()
    assert all(d.kind != "waste" for d in result.proposed_material_deltas)
    consumption = [
        d
        for d in result.proposed_material_deltas
        if d.stock_id == "fixture-tape-stock" and d.kind == "consume"
    ]
    assert sum(d.quantity for d in consumption) == 160
    assert all(d.unit == "mm" for d in consumption)


def test_two_distinct_confirmed_losses_debit_ten_each():
    request, process = case(20)
    first = request.material_transactions[0].model_copy(update={"quantity": 10})
    old_event = next(e for e in request.events if e.id == first.physical_event_id)
    old_evidence = next(e for e in request.evidence if e.id in old_event.evidence_ids)
    second_evidence = old_evidence.model_copy(
        update={
            "id": "synthetic-second-loss-evidence",
            "recorded_at": old_evidence.recorded_at + timedelta(seconds=1),
        }
    )
    second_event = old_event.model_copy(
        update={
            "id": "synthetic-second-loss-event",
            "recorded_at": second_evidence.recorded_at,
            "evidence_ids": (second_evidence.id,),
        }
    )
    second = first.model_copy(
        update={
            "id": "synthetic-second-loss-tx",
            "kind": "damage",
            "physical_event_id": second_event.id,
            "recorded_at": second_event.recorded_at,
        }
    )
    request = request.model_copy(
        update={
            "material_transactions": (first, second),
            "events": request.events + (second_event,),
            "evidence": request.evidence + (second_evidence,),
        }
    )
    result = run(request, process)
    assert result.status == "feasible", result.blockers
    assert (
        sum(
            d.quantity
            for d in result.proposed_material_deltas
            if d.kind == "consume" and d.unit == "mm"
        )
        == 160
    )


@pytest.mark.parametrize("second_kind", ["waste", "damage"])
def test_same_loss_event_cannot_be_debited_with_another_transaction_id(second_kind):
    request, process = case(20)
    first = request.material_transactions[0]
    second = first.model_copy(
        update={"id": "synthetic-duplicate-loss", "kind": second_kind}
    )
    request = request.model_copy(update={"material_transactions": (first, second)})
    result = run(request, process)
    assert result.status == "blocked"
    assert any(
        b.code == "stock_exhausted" and "duplicate" in b.message.lower()
        for b in result.blockers
    )


def test_connector_consume_transaction_verifies_completed_use_without_second_debit():
    request, process = case(20)
    completed = next(
        e
        for e in request.events
        if e.operation_id == "stand-joint-front-attach"
        and e.kind == "operation_confirmed"
    )
    consumed = request.material_transactions[0].model_copy(
        update={
            "id": "synthetic-completed-front-consumption",
            "kind": "consume",
            "quantity": 80,
            "physical_event_id": completed.id,
            "recorded_at": completed.recorded_at,
        }
    )
    request = request.model_copy(
        update={"material_transactions": (consumed,) + request.material_transactions}
    )
    result = run(request, process)
    assert result.status == "feasible", result.blockers
    assert (
        sum(
            d.quantity
            for d in result.proposed_material_deltas
            if d.kind == "consume" and d.unit == "mm"
        )
        == 160
    )


@pytest.mark.parametrize(
    "fault",
    [
        "overloss",
        "unknown_length",
        "unconfirmed_length",
        "wrong_unit",
        "source_region",
        "output_region",
        "unused_operation",
        "event_operation",
        "version",
        "missing_event",
        "unconfirmed_event",
        "empty_evidence",
        "future_evidence",
        "model_evidence",
        "unconfirmed_evidence",
        "remaining_mismatch",
        "salvage",
        "sheet_source",
    ],
)
def test_invalid_connector_loss_never_produces_a_feasible_preview(fault):
    request, process = case(20)
    tx = request.material_transactions[0]
    event = next(e for e in request.events if e.id == tx.physical_event_id)
    if fault == "overloss":
        request = change_loss(request, quantity=421)
    elif fault in ("unknown_length", "unconfirmed_length"):
        stocks = tuple(
            s.model_copy(
                update={
                    "remaining_length_mm": s.remaining_length_mm.model_copy(
                        update={"value": None, "confirmed": False, "source": "unknown"}
                        if fault == "unknown_length"
                        else {"confirmed": False}
                    )
                }
            )
            if s.id == tx.source_stock_id
            else s
            for s in request.base_plan.stocks
        )
        request = request.model_copy(
            update={
                "base_plan": request.base_plan.model_copy(update={"stocks": stocks})
            }
        )
    elif fault == "wrong_unit":
        request = change_loss(request, unit="mm2")
    elif fault == "source_region":
        request = change_loss(request, source_region_id="fixture-region")
    elif fault == "output_region":
        request = change_loss(
            request,
            output_region=m.Region(
                id="synthetic-false-output",
                geometry=m.Rect(x=0, y=0, width=1, height=20),
            ),
        )
    elif fault == "unused_operation":
        request = change_loss(request, operation_id="stand-inspect-cuts")
        request = change_loss_event(request, operation_id="stand-inspect-cuts")
    elif fault == "event_operation":
        request = change_loss_event(request, operation_id="stand-joint-rear-attach")
    elif fault == "version":
        request = change_loss(request, version_id="synthetic-wrong-version")
    elif fault == "missing_event":
        request = change_loss(request, physical_event_id="synthetic-missing-event")
    elif fault == "unconfirmed_event":
        request = change_loss_event(request, verification_state="unknown")
    elif fault == "empty_evidence":
        request = change_loss_event(request, evidence_ids=())
    elif fault == "future_evidence":
        request = change_loss_evidence(
            request, recorded_at=event.recorded_at + timedelta(seconds=1)
        )
    elif fault == "model_evidence":
        request = change_loss_evidence(
            request, provenance="model", verification_state="unknown"
        )
    elif fault == "unconfirmed_evidence":
        request = change_loss_evidence(request, verification_state="unknown")
    elif fault == "remaining_mismatch":
        request = request.model_copy(
            update={
                "remaining_stock": tuple(
                    s.model_copy(
                        update={
                            "remaining_length_mm": s.remaining_length_mm.model_copy(
                                update={"value": 420}
                            )
                        }
                    )
                    if s.id == tx.source_stock_id
                    else s
                    for s in request.remaining_stock
                )
            }
        )
    elif fault == "salvage":
        request = change_loss(request, kind="salvage")
    else:
        request = change_loss(request, source_stock_id="fixture-sheet")
    result = run(request, process)
    assert result.status == "blocked", (fault, result)
    assert result.plan is None and result.cost is None
    assert result.blockers
    if fault == "remaining_mismatch":
        assert any(
            b.code == "stock_exhausted" and "remaining" in b.message.lower()
            for b in result.blockers
        )
    elif fault == "salvage":
        assert any(
            b.code == "unsupported" and "salvage" in b.message.lower()
            for b in result.blockers
        )
    elif fault == "overloss":
        assert any(b.code == "stock_exhausted" for b in result.blockers)
