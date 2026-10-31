"""Synthetic software fixtures only. No physical build or test was performed."""

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from forma_compiler import CutProcess
from forma_renderer import StandParameters, compile_stand, render_manual
from forma_renderer.svg import dimension

from forma_domain import models as m


# measured() builds a confirmed calculated measurement for SYNTHETIC fixtures.
def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


def fixture(*, alternate=False):
    now = datetime(2026, 10, 30, tzinfo=UTC)
    unknown = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    evidence = tuple(
        m.Evidence(
            id=name,
            project_id="fixture-project",
            version_id="fixture-v1",
            kind="measurement",
            provenance="synthetic_fixture",
            recorded_at=now,
            description="SYNTHETIC software fixture only, not physically tested",
            verification_state="unknown",
        )
        for name in ("fixture-process", "fixture-tape", "fixture-fold")
    )
    width, height, angle, depth, stock_width, stock_height = (
        (100, 180, 55, 155, 260, 650) if alternate else (80, 150, 60, 140, 200, 550)
    )
    sheet = m.Stock(
        id="fixture-sheet",
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=measured(stock_width),
        height_mm=measured(stock_height),
        thickness_mm=measured(2),
        remaining_length_mm=unknown,
        usable_regions=(
            m.Region(
                id="fixture-region",
                geometry=m.Rect(x=0, y=0, width=stock_width, height=stock_height),
            ),
        ),
    )
    tape = m.Stock(
        id="fixture-tape-stock",
        kind="tape",
        material="other_supported",
        condition="usable",
        width_mm=measured(30),
        height_mm=unknown,
        thickness_mm=unknown,
        remaining_length_mm=measured(500),
    )
    profiles = tuple(
        m.JointProfile(
            id=f"fixture-{name}-profile",
            strategy=strategy,
            status="tested",
            material="cardboard",
            thickness_min_mm=1,
            thickness_max_mm=3,
            tolerated_error_mm=1,
            test_evidence_ids=(f"fixture-{name}",),
            limitations=("SYNTHETIC only",),
        )
        for name, strategy in (("tape", "tape"), ("fold", "fold_brace"))
    )
    limits = m.Constraints(
        device_mass_g=measured(180, "g"),
        support_angle_deg=measured(angle, "deg"),
        max_footprint_width_mm=measured(120),
        max_footprint_height_mm=measured(180),
        allowed_profile_ids=tuple(p.id for p in profiles),
    )
    request = m.CompilerInput(
        project_id="fixture-project",
        version_id="fixture-v1",
        created_at=now,
        candidate=m.DesignCandidate(
            id="fixture-candidate",
            family="tabletop_fixture_v1",
            support_angle_deg=angle,
            part_width_mm=width,
            part_height_mm=height,
            panel_count=3,
            stock_ids=(sheet.id, tape.id),
            profile_ids=tuple(p.id for p in profiles),
            assumptions=("SYNTHETIC only",),
        ),
        stocks=(sheet, tape),
        joint_profiles=profiles,
        constraints=limits,
        kerf_mm=2,
        edge_margin_mm=4,
        process_evidence_ids=("fixture-process",),
    )
    parameters = StandParameters(
        footprint_depth_mm=measured(depth),
        lip_mm=measured(15),
        device_width_mm=measured(70),
        device_thickness_mm=measured(8),
        device_contact_height_mm=measured(100),
        tape_overlap_mm=measured(10),
        tools_confirmed=True,
        joint_access_confirmed=True,
        device_label="SYNTHETIC phone specimen",
        test_duration_seconds=60,
        test_surface="SYNTHETIC flat desk",
        test_pass_criteria=("No slip or tip", "Three insertion/removal cycles"),
        profile_evidence=evidence[1:],
    )
    process = CutProcess(kerf_min_mm=2, edge_margin_min_mm=4, evidence=(evidence[0],))
    return request, parameters, process


def build(*, alternate=False):
    request, parameters, process = fixture(alternate=alternate)
    result = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert result.status == "accepted", result.blockers
    return result.plan, parameters, process


def manual(plan, parameters, process):
    return render_manual(
        plan,
        process=process,
        profile_evidence=parameters.profile_evidence,
        allow_synthetic=True,
    )


def _tape_readout(panel, operation):
    root = ET.fromstring(panel.svg)
    stock_id = operation.args.stock_id
    groups = [n for n in root.iter() if n.attrib.get("data-stock-id") == stock_id]
    assert len(groups) == 1
    ns = "http://www.w3.org/2000/svg"
    texts = ["".join(t.itertext()) for t in groups[0].iter(f"{{{ns}}}text")]
    joined = " ".join(texts)
    nums = [float(v) for v in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*mm", joined)]
    return texts, nums


def test_tape_panels_show_decreasing_remaining_from_plan():
    plan, parameters, process = build()
    result = manual(plan, parameters, process)
    assert result.status == "accepted"
    tape_ops = [o for o in plan.operations if o.type == "tape_joint"]
    assert len(tape_ops) == 3
    stock_id = tape_ops[0].args.stock_id
    assert all(o.args.stock_id == stock_id for o in tape_ops)
    width = tape_ops[0].args.length_mm
    assert width == pytest.approx(plan.parts[0].geometry.width)
    assert all(o.args.length_mm == pytest.approx(width) for o in tape_ops)
    initial = next(s for s in plan.stocks if s.id == stock_id).remaining_length_mm.value
    assert initial is not None
    tape_ids = {o.id for o in tape_ops}
    tape_panels = [p for p in result.panels if p.operation_id in tape_ids]
    assert len(tape_panels) == 3
    order = {o.id: idx for idx, o in enumerate(plan.operations)}
    tape_panels.sort(key=lambda p: order[p.operation_id])
    tape_ops_sorted = sorted(tape_ops, key=lambda o: order[o.id])
    remainings = []
    for k, (panel, op) in enumerate(zip(tape_panels, tape_ops_sorted), start=1):
        texts, nums = _tape_readout(panel, op)
        assert len(nums) == 3
        used_before, this_step, remaining = nums
        assert texts[0].startswith("tape used before")
        assert dimension((k - 1) * width) in texts[0]
        assert dimension(width) in texts[1]
        assert dimension(initial - k * width) in texts[2]
        assert used_before == pytest.approx((k - 1) * width)
        assert this_step == pytest.approx(width)
        assert remaining == pytest.approx(initial - k * width)
        remainings.append(remaining)
    assert remainings[0] > remainings[1] > remainings[2]
    bill_remaining = next(
        b.quantity for b in result.bill_of_materials if b.id == f"{stock_id}-remaining"
    )
    assert remainings[-1] == pytest.approx(bill_remaining)


def test_cut_panel_offcut_and_waste_caption():
    plan, parameters, process = build()
    result = manual(plan, parameters, process)
    cut = result.panels[0]
    root = ET.fromstring(cut.svg)
    assert not [n for n in root.iter() if "data-region-id" in n.attrib]
    assert "shaded remainder = waste" in cut.svg
    cut_op = next(o for o in plan.operations if o.type == "cut_rect")
    source_region = next(
        r
        for s in plan.stocks
        for r in s.usable_regions
        if r.id == cut_op.args.source_region_id
    )
    sg = source_region.geometry
    offcut_geo = {"x": 120, "y": 400, "width": 40, "height": 80, "rotation_deg": 0}
    ox, oy, ow, oh = (
        offcut_geo["x"],
        offcut_geo["y"],
        offcut_geo["width"],
        offcut_geo["height"],
    )
    assert ox >= sg.x and oy >= sg.y
    assert ox + ow <= sg.x + sg.width and oy + oh <= sg.y + sg.height
    for part in plan.parts:
        pg = part.geometry
        overlaps = not (
            ox + ow <= pg.x
            or pg.x + pg.width <= ox
            or oy + oh <= pg.y
            or pg.y + pg.height <= oy
        )
        assert not overlaps, f"offcut overlaps {part.id}"
    data = plan.model_dump()
    offcut = {"id": "fixture-offcut-1", "geometry": dict(offcut_geo)}
    data["operations"][0]["effects"]["created_offcuts"] = (offcut,)
    injected = m.BuildPlan.model_validate(data)
    rendered = manual(injected, parameters, process)
    assert rendered.status == "accepted", (
        "hand-injected offcut should validate; if blocked, validation rejects hand-injected offcuts"
    )
    cut2 = rendered.panels[0]
    root2 = ET.fromstring(cut2.svg)
    regions = [
        n for n in root2.iter() if n.attrib.get("data-region-id") == "fixture-offcut-1"
    ]
    assert len(regions) == 1
    assert [
        n.attrib.get("data-region-id")
        for n in root2.iter()
        if "data-region-id" in n.attrib
    ] == ["fixture-offcut-1"]
    ns = "http://www.w3.org/2000/svg"
    label = " ".join("".join(t.itertext()) for t in regions[0].iter(f"{{{ns}}}text"))
    assert "fixture-offcut-1" in label
    assert f"{dimension(ow)} x {dimension(oh)} mm" in label
    rect = regions[0].find(f"{{{ns}}}rect")
    assert rect is not None and rect.attrib["fill"] == "none"
    sheet = next(s for s in plan.stocks if s.id == cut_op.args.stock_id)
    scale = min(740 / sheet.width_mm.value, 370 / sheet.height_mm.value)
    assert float(rect.attrib["x"]) == pytest.approx(ox * scale)
    assert float(rect.attrib["y"]) == pytest.approx(oy * scale)
    assert float(rect.attrib["width"]) == pytest.approx(ow * scale)
    assert float(rect.attrib["height"]) == pytest.approx(oh * scale)
    assert (
        "shaded remainder = waste except labelled offcut regions are remaining stock"
        in cut2.svg
    )
    assert "not available offcut stock" not in cut2.svg


@pytest.mark.parametrize("alternate", [False, True])
def test_two_meaningful_parameterizations_and_complete_manual(alternate):
    plan, parameters, process = build(alternate=alternate)
    result = manual(plan, parameters, process)
    assert result.status == "accepted", result.blockers
    assert len(result.panels) == len(plan.operations) == 8
    assert result.physical_verification == "not_attempted"
    assert (
        sum(
            b.quantity
            for b in result.bill_of_materials
            if b.id == "fixture-tape-stock-consumed"
        )
        == 3 * plan.parts[0].geometry.width
    )
    assert any(
        b.id == "fixture-sheet-waste" and b.quantity > 0
        for b in result.bill_of_materials
    )
    for panel in result.panels:
        root = ET.fromstring(panel.svg)
        assert root.attrib["data-operation-id"] == panel.operation_id
        assert {
            node.attrib["data-part-id"]
            for node in root.iter()
            if "data-part-id" in node.attrib
        } == set(panel.part_ids)
        # checkpoint ids are rendered inline in each panel
        assert all(checkpoint in panel.svg for checkpoint in panel.checkpoint_ids)
        assert "SYNTHETIC SOFTWARE FIXTURE" in panel.svg
        assert "Requires user confirmation" in panel.svg
        assert panel.tools
    assert "data-stock-id" in result.panels[0].svg
    assert "marker-end" in result.panels[2].svg
    assert "data-joint-id" in result.panels[3].svg


def test_alternate_changes_dimensions_angle_and_stock_allocation():
    a, _, _ = build()
    b, _, _ = build(alternate=True)
    assert a.parts[0].geometry.width != b.parts[0].geometry.width
    assert a.parts[2].geometry.height != b.parts[2].geometry.height
    assert a.constraints.support_angle_deg != b.constraints.support_angle_deg
    assert a.stocks[0].width_mm != b.stocks[0].width_mm


def test_byte_identity_and_version_independent_cache():
    plan, parameters, process = build()
    first = manual(plan, parameters, process)
    assert first == manual(plan, parameters, process)
    data = plan.model_dump()
    data.update(
        version_id="fixture-v2",
        parent_version_id="fixture-v1",
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    revised = m.BuildPlan.model_validate(data)
    assert first == manual(revised, parameters, process)


def test_geometry_change_changes_affected_panels_but_reuses_fold():
    request, parameters, process = fixture()
    first = compile_stand(request, parameters, process=process, allow_synthetic=True)
    changed = StandParameters.model_validate(
        parameters.model_dump() | {"footprint_depth_mm": measured(150)}
    )
    second = compile_stand(request, changed, process=process, allow_synthetic=True)
    assert first.status == second.status == "accepted"
    a = manual(first.plan, parameters, process)
    b = manual(second.plan, changed, process)
    assert a.panels[0].dependency_hash != b.panels[0].dependency_hash
    assert a.panels[2].svg == b.panels[2].svg  # support fold geometry unchanged
    assert a.panels[3].dependency_hash != b.panels[3].dependency_hash


def test_default_rejects_synthetic_evidence_and_missing_process():
    request, parameters, process = fixture()
    assert compile_stand(request, parameters, process=process).status == "blocked"
    assert compile_stand(request, parameters, allow_synthetic=True).status == "blocked"
    plan, _, _ = build()
    assert not render_manual(
        plan, process=process, profile_evidence=parameters.profile_evidence
    ).panels
    assert not render_manual(plan, process=process, allow_synthetic=True).panels


@pytest.mark.parametrize(
    "field", ["lip_mm", "device_width_mm", "footprint_depth_mm", "tape_overlap_mm"]
)
def test_unknown_required_measurements_block(field):
    request, parameters, process = fixture()
    data = parameters.model_dump()
    data[field] = m.Measurement(
        value=None, unit="mm", source="unknown", confirmed=False
    )
    result = compile_stand(
        request,
        StandParameters.model_validate(data),
        process=process,
        allow_synthetic=True,
    )
    assert result.status == "needs_measurement" and result.plan is None


def test_exhausted_stock_and_oversize_device_block():
    request, parameters, process = fixture()
    data = request.model_dump()
    data["stocks"][0]["height_mm"]["value"] = 200
    data["stocks"][0]["usable_regions"][0]["geometry"]["height"] = 200
    result = compile_stand(
        m.CompilerInput.model_validate(data),
        parameters,
        process=process,
        allow_synthetic=True,
    )
    assert result.status == "blocked"
    data = parameters.model_dump()
    data["device_width_mm"]["value"] = 200
    assert (
        compile_stand(
            request,
            StandParameters.model_validate(data),
            process=process,
            allow_synthetic=True,
        ).status
        == "blocked"
    )


def test_escape_user_text_and_unresolved_profile_evidence():
    plan, parameters, process = build()
    data = plan.model_dump()
    data["operations"][-1]["args"]["device_label"] = '<script>alert("x")</script>'
    result = manual(m.BuildPlan.model_validate(data), parameters, process)
    assert result.status == "accepted"
    assert "<script>" not in result.panels[-1].svg
    assert "&lt;script&gt;" in result.panels[-1].svg
    assert (
        render_manual(plan, process=process, allow_synthetic=True).status == "blocked"
    )


@pytest.mark.parametrize(
    "change",
    ["zero_support", "missing_checkpoint", "unknown_mass", "wrong_joint", "wrong_fold"],
)
def test_malformed_supported_ids_block_without_crashing(change):
    plan, parameters, process = build()
    data = plan.model_dump()
    if change == "zero_support":
        data["parts"][0]["features"][0]["geometry"]["y"] = 0
    elif change == "missing_checkpoint":
        data["checkpoints"] = tuple(
            c
            for c in data["checkpoints"]
            if c["after_operation_id"] != "stand-inspect-cuts"
        )
        data["operations"][1]["args"]["checkpoint_id"] = "stand-function-check"
    elif change == "unknown_mass":
        data["operations"][-1]["args"]["mass_g"] = None
    elif change == "wrong_joint":
        data["joints"][0]["part_ids"] = ("stand-support", "stand-brace")
    else:
        data["operations"][2]["args"]["angle_deg"] = 70
    result = manual(m.BuildPlan.model_validate(data), parameters, process)
    assert result.status == "blocked" and not result.panels


def test_ambiguous_ids_and_candidate_reference_fail_as_blockers():
    request, parameters, process = fixture()
    data = request.model_dump()
    data["joint_profiles"] += (data["joint_profiles"][0],)
    result = compile_stand(
        m.CompilerInput.model_validate(data),
        parameters,
        process=process,
        allow_synthetic=True,
    )
    assert result.status == "blocked" and result.blockers[0].code == "invalid_reference"
    data = request.model_dump()
    data["constraints"]["allowed_profile_ids"] = ("missing-profile",)
    result = compile_stand(
        m.CompilerInput.model_validate(data),
        parameters,
        process=process,
        allow_synthetic=True,
    )
    assert result.status == "blocked" and result.blockers[0].code == "invalid_reference"
    duplicate = StandParameters.model_validate(
        parameters.model_dump() | {"profile_evidence": parameters.profile_evidence * 2}
    )
    assert (
        compile_stand(request, duplicate, process=process, allow_synthetic=True).status
        == "blocked"
    )
    data = request.model_dump()
    data["stocks"][0]["id"] = "stand-support"
    data["candidate"]["stock_ids"] = ("stand-support", "fixture-tape-stock")
    result = compile_stand(
        m.CompilerInput.model_validate(data),
        parameters,
        process=process,
        allow_synthetic=True,
    )
    assert result.status == "blocked" and result.blockers[0].code == "invalid_reference"


def test_long_instructions_expand_panel_without_overlapping_drawing():
    plan, parameters, process = build()
    data = plan.model_dump()
    data["operations"][-1]["args"]["device_label"] = "long specimen description " * 70
    result = manual(m.BuildPlan.model_validate(data), parameters, process)
    root = ET.fromstring(result.panels[-1].svg)
    assert float(root.attrib["viewBox"].split()[-1]) > 900


def test_unused_stock_remains_available_in_bill():
    request, parameters, process = fixture()
    data = request.model_dump()
    spare = dict(data["stocks"][0])
    spare["id"] = "unused-sheet"
    spare["usable_regions"] = tuple(
        dict(r, id="unused-region") for r in spare["usable_regions"]
    )
    data["stocks"] += (spare,)
    compiled = compile_stand(
        m.CompilerInput.model_validate(data),
        parameters,
        process=process,
        allow_synthetic=True,
    )
    result = manual(compiled.plan, parameters, process)
    entries = {item.id: item for item in result.bill_of_materials}
    assert entries["unused-sheet-waste"].quantity == 0
    assert entries["unused-sheet-remaining"].quantity == 200 * 550


def test_renderer_revalidates_model_copy():
    plan, parameters, process = build()
    result = manual(plan.model_copy(update={"parts": ()}), parameters, process)
    assert result.status == "blocked" and not result.panels


def test_overdrawn_tape_stock_blocks_manual():
    plan, parameters, process = build()
    tape_ops = [o for o in plan.operations if o.type == "tape_joint"]
    assert len(tape_ops) == 3
    stock_id = tape_ops[0].args.stock_id
    width = tape_ops[0].args.length_mm
    total = sum(o.args.length_mm for o in tape_ops)
    initial = 2 * width
    assert 0 < width < initial < total
    data = plan.model_dump()
    for stock in data["stocks"]:
        if stock["id"] == stock_id:
            stock["remaining_length_mm"]["value"] = initial
    overdrawn = m.BuildPlan.model_validate(data)
    result = manual(overdrawn, parameters, process)
    assert result.status != "accepted"
    assert result.blockers
    assert any(b.code == "stock_exhausted" for b in result.blockers)
