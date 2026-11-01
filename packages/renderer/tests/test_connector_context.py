"""SYNTHETIC reconciled connector forecasts, never physical proof."""

import json
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
from forma_compiler import CutProcess
from forma_renderer import (
    ConnectorContext,
    StandParameters,
    compile_stand,
    diff_manuals,
    render_manual,
    stand_continuation_blockers,
)
from forma_replanner import simulate_patch

from forma_domain import models as m


def case(loss=20, *, unknown_unused=False):
    raw = json.loads(
        (
            Path(__file__).resolve().parents[3] / "fixtures/missing_connector.json"
        ).read_text(encoding="utf-8")
    )
    request = m.CompilerInput.model_validate(raw["compiler_input"])
    parameters = StandParameters.model_validate(raw["stand_parameters"])
    process = CutProcess.model_validate(raw["process"])
    values = deepcopy(raw["scenarios"][0]["replanner_input"])
    if unknown_unused:
        tape = next(s for s in request.stocks if s.kind == "tape")
        unused = tape.model_copy(
            update={
                "id": "synthetic-unused-tape",
                "remaining_length_mm": m.Measurement(
                    value=None, unit="mm", source="unknown", confirmed=False
                ),
            }
        )
        request = request.model_copy(update={"stocks": request.stocks + (unused,)})
        values["remaining_stock"].append(unused.model_dump(mode="json"))
    compiled = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert compiled.status == "accepted", compiled.blockers
    values["base_plan"] = compiled.plan
    values["material_transactions"][0]["quantity"] = loss
    for stock in values["remaining_stock"]:
        if stock["id"] == "fixture-tape-stock":
            stock["remaining_length_mm"]["value"] = 420 - loss
    snapshot = m.ReplannerInput.model_validate(values)
    before = deepcopy(snapshot.model_dump())
    result = simulate_patch(
        snapshot,
        process=process,
        allow_synthetic=True,
        family_validator=stand_continuation_blockers,
    )
    assert snapshot.model_dump() == before
    assert result.status == "feasible", result.blockers
    context = ConnectorContext(
        project_id=result.plan.project_id,
        plan_version_id=result.plan.version_id,
        observed_version_id=compiled.plan.version_id,
        remaining_connectors=tuple(
            s for s in snapshot.remaining_stock if s.kind in ("tape", "cord")
        ),
        completed_operation_ids=result.preserved_operation_ids,
    )
    return result.plan, parameters, process, context, snapshot


def render(plan, parameters, process, context=None):
    before = deepcopy(
        (
            plan.model_dump(),
            parameters.model_dump(),
            process.model_dump(),
            context.model_dump() if context is not None else None,
        )
    )
    result = render_manual(
        plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
        connector_context=context,
    )
    after = (
        plan.model_dump(),
        parameters.model_dump(),
        process.model_dump(),
        context.model_dump() if context is not None else None,
    )
    assert after == before
    assert result.physical_verification == "not_attempted"
    assert all("SYNTHETIC" in p.svg for p in result.panels)
    return result


def quantities(manual):
    return {b.id: b.quantity for b in manual.bill_of_materials}


def readout(panel):
    root = ET.fromstring(panel.svg)
    texts = [
        "".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text")
    ]
    return [
        float(re.search(r"(-?\d+(?:\.\d+)?) mm", t).group(1))
        for t in texts
        if t.startswith(("expected tape before:", "this step:", "expected tape after:"))
    ]


def test_observed_context_forecasts_only_future_join_panels_and_bom():
    plan, parameters, process, context, snapshot = case()
    before = deepcopy(snapshot.model_dump())
    nominal = render(plan, parameters, process)
    observed = render(plan, parameters, process, context)
    assert nominal.status == observed.status == "accepted"
    assert nominal.resource_basis == "plan" and observed.resource_basis == "mixed"
    assert quantities(nominal)["fixture-tape-stock-remaining"] == 260
    bill = quantities(observed)
    assert bill["fixture-tape-stock-current"] == 400
    assert bill["fixture-tape-stock-future-use"] == 160
    assert bill["fixture-tape-stock-remaining"] == 240
    assert readout(observed.panels[4]) == [400, 80, 320]
    assert readout(observed.panels[5]) == [320, 80, 240]
    assert observed.panels[3].svg == nominal.panels[3].svg
    assert observed.panels[3].dependency_hash == nominal.panels[3].dependency_hash
    change = diff_manuals(nominal, observed)
    assert change.changed == (4, 5)
    assert change.unchanged == (0, 1, 2, 3, 6, 7)
    assert change.added == change.removed == ()
    assert snapshot.model_dump() == before


def test_actual_different_loss_changes_only_future_forecast_hashes():
    first = case(20)
    second = case(30)
    old = render(*first[:3], first[3])
    new = render(*second[:3], second[3])
    assert quantities(new)["fixture-tape-stock-current"] == 390
    assert quantities(new)["fixture-tape-stock-remaining"] == 230
    assert readout(new.panels[4]) == [390, 80, 310]
    assert readout(new.panels[5]) == [310, 80, 230]
    assert diff_manuals(old, new).changed == (4, 5)


def test_unknown_unused_connector_stays_unknown_in_current_and_remaining_bom():
    plan, parameters, process, context, _ = case(unknown_unused=True)
    manual = render(plan, parameters, process, context)
    assert manual.status == "accepted", manual.blockers
    bill = quantities(manual)
    assert bill["synthetic-unused-tape-current"] is None
    assert bill["synthetic-unused-tape-remaining"] is None


def test_unconfirmed_unused_number_is_not_an_observed_balance():
    plan, parameters, process, context, _ = case(unknown_unused=True)
    connectors = tuple(
        s.model_copy(
            update={
                "remaining_length_mm": m.Measurement(
                    value=1000, unit="mm", source="user_ruler", confirmed=False
                )
            }
        )
        if s.id == "synthetic-unused-tape"
        else s
        for s in context.remaining_connectors
    )
    context = context.model_copy(update={"remaining_connectors": connectors})
    manual = render(plan, parameters, process, context)
    assert manual.status == "accepted", manual.blockers
    assert quantities(manual)["synthetic-unused-tape-current"] is None
    assert quantities(manual)["synthetic-unused-tape-remaining"] is None


def test_new_photo_reference_does_not_change_connector_identity():
    plan, parameters, process, context, _ = case()
    context = update_stock(context, image_ids=("synthetic-new-photo",))
    manual = render(plan, parameters, process, context)
    assert manual.status == "accepted", manual.blockers
    assert quantities(manual)["fixture-tape-stock-remaining"] == 240


def update_stock(context, **changes):
    return context.model_copy(
        update={
            "remaining_connectors": tuple(
                s.model_copy(update=changes) if s.id == "fixture-tape-stock" else s
                for s in context.remaining_connectors
            )
        }
    )


@pytest.mark.parametrize(
    "fault",
    [
        "project",
        "plan_version",
        "observed_version",
        "duplicate_stock",
        "missing_stock",
        "extra_stock",
        "kind",
        "material",
        "dimension",
        "unusable",
        "unknown_used",
        "unconfirmed_used",
        "unknown_completed",
        "duplicate_completed",
        "not_dependency_closed",
        "exceeds_reconciled_maximum",
        "insufficient_future",
    ],
)
def test_invalid_connector_context_blocks_without_partial_manual(fault):
    plan, parameters, process, context, _ = case()
    if fault in ("project", "plan_version", "observed_version"):
        field = {
            "project": "project_id",
            "plan_version": "plan_version_id",
            "observed_version": "observed_version_id",
        }[fault]
        context = context.model_copy(update={field: "synthetic-wrong-scope"})
    elif fault == "duplicate_stock":
        context = context.model_copy(
            update={"remaining_connectors": context.remaining_connectors * 2}
        )
    elif fault == "missing_stock":
        context = context.model_copy(update={"remaining_connectors": ()})
    elif fault == "extra_stock":
        context = context.model_copy(
            update={
                "remaining_connectors": context.remaining_connectors
                + (
                    context.remaining_connectors[0].model_copy(
                        update={"id": "synthetic-unallocated-source"}
                    ),
                )
            }
        )
    elif fault in ("kind", "material", "dimension", "unusable"):
        changes = {
            "kind": {"kind": "cord"},
            "material": {"material": "other_supported"},
            "dimension": {
                "width_mm": m.Measurement(
                    value=99, unit="mm", source="calculated", confirmed=True
                )
            },
            "unusable": {"condition": "damaged"},
        }[fault]
        # The original tape material is already other_supported; choose cardboard to differ.
        if fault == "material":
            changes = {"material": "cardboard"}
        context = update_stock(context, **changes)
    elif fault in (
        "unknown_used",
        "unconfirmed_used",
        "exceeds_reconciled_maximum",
        "insufficient_future",
    ):
        length = context.remaining_connectors[0].remaining_length_mm
        changes = {
            "unknown_used": {"value": None, "confirmed": False, "source": "unknown"},
            "unconfirmed_used": {"confirmed": False},
            "exceeds_reconciled_maximum": {"value": 430},
            "insufficient_future": {"value": 100},
        }[fault]
        context = update_stock(
            context, remaining_length_mm=length.model_copy(update=changes)
        )
    elif fault == "unknown_completed":
        context = context.model_copy(
            update={
                "completed_operation_ids": context.completed_operation_ids
                + ("synthetic-no-such-operation",)
            }
        )
    elif fault == "duplicate_completed":
        context = context.model_copy(
            update={"completed_operation_ids": context.completed_operation_ids * 2}
        )
    else:
        context = context.model_copy(
            update={"completed_operation_ids": ("stand-joint-front-attach",)}
        )
    manual = render(plan, parameters, process, context)
    expected_status = (
        "needs_measurement"
        if fault in ("unknown_used", "unconfirmed_used")
        else "blocked"
    )
    assert manual.status == expected_status and manual.panels == ()
    assert manual.blockers
    if fault in ("unknown_used", "unconfirmed_used"):
        assert any(b.code == "missing_measurement" for b in manual.blockers)
    if fault in ("exceeds_reconciled_maximum", "insufficient_future"):
        assert any(b.code == "stock_exhausted" for b in manual.blockers)
