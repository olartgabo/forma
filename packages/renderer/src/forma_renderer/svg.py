"""Deterministic, escaped SVG panels from validated stand operation data."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from hashlib import sha256
from math import cos, hypot, radians, sin
from textwrap import wrap

from forma_compiler import CutProcess, validate_plan

from forma_domain import models as m

from .template import profile_evidence_valid


@dataclass(frozen=True)
class BillItem:
    id: str
    stock_id: str
    quantity: float
    unit: str
    description: str


@dataclass(frozen=True)
class Panel:
    operation_id: str
    part_ids: tuple[str, ...]
    checkpoint_ids: tuple[str, ...]
    dependency_hash: str
    svg: str
    tools: tuple[str, ...]


@dataclass(frozen=True)
class Manual:
    status: str
    panels: tuple[Panel, ...]
    bill_of_materials: tuple[BillItem, ...]
    blockers: tuple[m.Blocker, ...]
    physical_verification: str = "not_attempted"


def number(value):
    return format(value, ".6f").rstrip("0").rstrip(".") or "0"


def dimension(value):
    return format(value, ".2f").rstrip("0").rstrip(".") or "0"


def element(parent, name, **attrs):
    return ET.SubElement(
        parent,
        name,
        {key.replace("_", "-"): str(value) for key, value in attrs.items()},
    )


def text(parent, x, y, value, size=16, **attrs):
    node = element(parent, "text", x=x, y=y, font_size=size, **attrs)
    node.text = str(value)
    return node


def lines(parent, x, y, value, width=90, size=16):
    for index, line in enumerate(wrap(value, width=width)):
        text(parent, x, y + index * (size + 6), line, size)


def tools_for(operation):
    return {
        "cut_rect": ("ruler", "confirmed cutting tool", "cutting mat"),
        "fold": ("ruler", "confirmed folding tool"),
        "tape_joint": ("ruler", "tape", "confirmed cutting tool"),
        "inspect": ("ruler", "protractor", "camera"),
        "functional_test": ("named device", "timer", "camera"),
    }[operation.type]


def instruction(operation, plan):
    if operation.type == "cut_rect":
        if operation.effects.created_offcuts:
            return f"Confirm all measurements and safe tools. Cut the three labelled panels; kerf {number(operation.args.kerf_mm)} mm, edge margin {number(operation.args.edge_margin_mm)} mm. Labelled offcut regions are remaining stock; other unallocated sheet material is waste."
        return f"Confirm all measurements and safe tools. Cut the three labelled panels; kerf {number(operation.args.kerf_mm)} mm, edge margin {number(operation.args.edge_margin_mm)} mm. Unallocated sheet material is waste, not available offcut stock."
    if operation.type == "fold":
        a = operation.args
        return f"Fold stand-support on stand-lip-fold at {number(a.start_y_mm)} mm from the top, {number(a.angle_deg)} deg valley toward front. Check cracking and actual fold allowance manually."
    if operation.type == "tape_joint":
        return (
            f"Attach {operation.args.joint_id} using {number(operation.args.length_mm)} mm of {operation.args.stock_id}. "
            + " ".join(operation.preconditions.human_checks)
            + " Removal may damage sheet material."
        )
    if operation.type == "functional_test":
        a = operation.args
        return (
            f"Test {a.device_label}, {number(a.mass_g)} g, for {number(a.duration_seconds)} seconds on {a.surface}. Record observed pass/fail. "
            + "; ".join(a.pass_criteria)
        )
    return next(
        c.description for c in plan.checkpoints if c.after_operation_id == operation.id
    )


def flat_view(root, plan, operation, selected, *, stock=False):
    parts = [p for p in plan.parts if p.id in selected]
    if stock:
        source = next(s for s in plan.stocks if s.id == parts[0].source_stock_id)
        width, height = source.width_mm.value, source.height_mm.value
        scale = min(740 / width, 370 / height)
        group = element(
            root, "g", transform="translate(70 210)", data_stock_id=source.id
        )
        element(
            group,
            "rect",
            x=0,
            y=0,
            width=number(width * scale),
            height=number(height * scale),
            fill="#eeeeee",
            stroke="#111",
            stroke_width=2,
        )
        offcuts = operation.effects.created_offcuts
        if offcuts:
            caption = f"{source.id}: {number(width)} x {number(height)} mm; shaded remainder = waste except labelled offcut regions are remaining stock"
        else:
            caption = f"{source.id}: {number(width)} x {number(height)} mm; shaded remainder = waste"
        text(group, 0, -18, caption)
        for index, p in enumerate(parts):
            rect = p.geometry
            pg = element(group, "g", data_part_id=p.id)
            element(
                pg,
                "rect",
                x=number(rect.x * scale),
                y=number(rect.y * scale),
                width=number(rect.width * scale),
                height=number(rect.height * scale),
                fill="white",
                stroke="#111",
                stroke_width=2,
                stroke_dasharray="7 3",
            )
            text(
                pg,
                number((rect.x + rect.width / 2) * scale),
                number((rect.y + rect.height / 2) * scale),
                str(index + 1),
                22,
            )
            text(root, 420, 260 + index * 95, f"{index + 1}. {p.id}", 19)
            text(
                root,
                420,
                285 + index * 95,
                f"{dimension(rect.width)} x {dimension(rect.height)} mm",
                17,
            )
            text(
                root,
                420,
                308 + index * 95,
                f"Stock origin ({dimension(rect.x)}, {dimension(rect.y)}) mm",
                14,
            )
        for region in offcuts:
            geo = region.geometry
            og = element(group, "g", data_region_id=region.id)
            element(
                og,
                "rect",
                x=number(geo.x * scale),
                y=number(geo.y * scale),
                width=number(geo.width * scale),
                height=number(geo.height * scale),
                fill="none",
                stroke="#111",
                stroke_width=2,
                stroke_dasharray="3 3",
            )
            text(
                og,
                number((geo.x + geo.width / 2) * scale),
                number((geo.y + geo.height / 2) * scale),
                f"{region.id} {dimension(geo.width)} x {dimension(geo.height)} mm",
                12,
            )
    else:
        for index, p in enumerate(parts):
            scale = min(200 / p.geometry.width, 315 / p.geometry.height)
            group = element(
                root,
                "g",
                transform=f"translate({65 + index * 265} 225)",
                data_part_id=p.id,
            )
            width, height = p.geometry.width * scale, p.geometry.height * scale
            element(
                group,
                "rect",
                x=0,
                y=0,
                width=number(width),
                height=number(height),
                fill="white",
                stroke="#111",
                stroke_width=2,
            )
            text(group, 0, -15, p.id, 17)
            text(
                group,
                0,
                number(height + 24),
                f"{dimension(p.geometry.width)} x {dimension(p.geometry.height)} mm",
                14,
            )
            for feature in p.features:
                y = feature.geometry.y * scale
                element(
                    group,
                    "line",
                    x1=0,
                    y1=number(y),
                    x2=number(width),
                    y2=number(y),
                    stroke="#111",
                    stroke_width=2,
                    stroke_dasharray="8 4",
                    data_feature_id=feature.id,
                )
                text(
                    group,
                    0,
                    number(y - 9),
                    f"fold at {number(feature.geometry.y)} mm",
                    13,
                )
                if operation.type == "fold":
                    element(
                        group,
                        "path",
                        d=f"M {number(width + 16)} {number(y + 12)} q 45 -10 0 -42",
                        fill="none",
                        stroke="#111",
                        stroke_width=2,
                        marker_end="url(#arrow)",
                    )


def side_view(root, plan, operation, attached_before):
    parts = {p.id: p for p in plan.parts}
    support = parts["stand-support"]
    length = support.features[0].geometry.y
    depth = parts["stand-base"].geometry.height
    theta = radians(plan.constraints.support_angle_deg.value)
    reach, rise = length * cos(theta), length * sin(theta)
    scale = min(400 / depth, 300 / rise)
    start = (120, 555)
    apex = (120 + reach * scale, 555 - rise * scale)
    rear = (120 + depth * scale, 555)
    text(
        root,
        85,
        210,
        "Side elevation; nominal zero-thickness geometry (not a load rating)",
        16,
    )
    for index, (pid, p1, p2) in enumerate(
        (
            ("stand-base", start, rear),
            ("stand-support", start, apex),
            ("stand-brace", apex, rear),
        )
    ):
        group = element(root, "g", data_part_id=pid)
        element(
            group,
            "line",
            x1=number(p1[0]),
            y1=number(p1[1]),
            x2=number(p2[0]),
            y2=number(p2[1]),
            stroke="#111",
            stroke_width=5,
        )
        text(
            group,
            number((p1[0] + p2[0]) / 2 + 8),
            number((p1[1] + p2[1]) / 2 - 12),
            f"P{index + 1}",
            14,
        )
        text(
            root,
            610,
            500 + index * 30,
            f"P{index + 1} {pid}: {dimension(length if pid == 'stand-support' else parts[pid].geometry.height)} mm",
            13,
        )
    lip_length = support.geometry.height - length
    lip_end = (
        start[0] - sin(theta) * lip_length * scale,
        start[1] - cos(theta) * lip_length * scale,
    )
    element(
        root,
        "line",
        x1=start[0],
        y1=start[1],
        x2=number(lip_end[0]),
        y2=number(lip_end[1]),
        stroke="#111",
        stroke_width=5,
        data_feature_id="stand-lip-fold",
    )
    text(
        root,
        85,
        590,
        f"Support angle {number(plan.constraints.support_angle_deg.value)} deg; width {number(support.geometry.width)} mm; retaining lip {number(lip_length)} mm",
        15,
    )
    current = operation.args.joint_id if operation.type == "tape_joint" else None
    for index, (joint, point) in enumerate(
        (
            ("stand-joint-front", start),
            ("stand-joint-rear", rear),
            ("stand-joint-apex", apex),
        )
    ):
        group = element(root, "g", data_joint_id=joint)
        active = joint in attached_before or joint == current
        element(
            group,
            "circle",
            cx=number(point[0]),
            cy=number(point[1]),
            r=11,
            fill="white",
            stroke="#111",
            stroke_width=3,
            stroke_dasharray="none" if active else "3 3",
        )
        text(group, number(point[0] - 4), number(point[1] + 4), index + 1, 12)
        text(root, 610, 280 + index * 65, f"{index + 1}. {joint}", 14)
        text(
            root,
            610,
            300 + index * 65,
            (
                ": attach now"
                if joint == current
                else ": previously attached"
                if active
                else ": not yet joined"
            ),
            13,
        )
        if joint == current:
            element(
                group,
                "line",
                x1=number(point[0] + 50),
                y1=number(point[1] - 65),
                x2=number(point[0] + 10),
                y2=number(point[1] - 14),
                stroke="#111",
                stroke_width=2,
                marker_end="url(#arrow)",
            )


def template_valid(plan):
    """Check the renderer's exact supported geometry/sequence before SVG math."""
    parts = {p.id: p for p in plan.parts}
    if set(parts) != {"stand-support", "stand-base", "stand-brace"}:
        return False
    support_part = parts["stand-support"]
    if len(support_part.features) != 1:
        return False
    feature = support_part.features[0]
    support = feature.geometry.y
    lip = support_part.geometry.height - support
    angle_m = plan.constraints.support_angle_deg
    if (
        feature.id != "stand-lip-fold"
        or feature.kind != "fold"
        or feature.geometry.x != 0
        or feature.geometry.width != support_part.geometry.width
        or abs(feature.geometry.height - lip) > 1e-7
    ):
        return False
    if (
        support <= 0
        or lip <= 0
        or angle_m.value is None
        or not angle_m.confirmed
        or not 0 < angle_m.value < 90
    ):
        return False
    angle = radians(angle_m.value)
    depth = parts["stand-base"].geometry.height
    if depth <= support * cos(angle) or any(
        p.geometry.width != support_part.geometry.width for p in parts.values()
    ):
        return False
    expected_brace = hypot(depth - support * cos(angle), support * sin(angle))
    if abs(parts["stand-brace"].geometry.height - expected_brace) > 1e-6:
        return False
    expected = (
        ("stand-cut-panels", "cut_rect"),
        ("stand-inspect-cuts", "inspect"),
        ("stand-fold-lip", "fold"),
        ("stand-joint-front-attach", "tape_joint"),
        ("stand-joint-rear-attach", "tape_joint"),
        ("stand-joint-apex-attach", "tape_joint"),
        ("stand-inspect-fit", "inspect"),
        ("stand-functional-test", "functional_test"),
    )
    if tuple((o.id, o.type) for o in plan.operations) != expected:
        return False
    all_parts = tuple(p.id for p in plan.parts)
    if any(
        plan.operations[index].part_ids != all_parts for index in (1, 6, 7)
    ) or plan.operations[2].part_ids != ("stand-support",):
        return False
    if any(
        not any(
            c.after_operation_id == o.id and c.id == o.args.checkpoint_id
            for c in plan.checkpoints
        )
        for o in plan.operations
        if o.type in ("inspect", "functional_test")
    ):
        return False
    fold = plan.operations[2].args
    if (
        fold.part_id != support_part.id
        or fold.feature_id != feature.id
        or fold.start_x_mm != 0
        or fold.end_x_mm != support_part.geometry.width
        or fold.start_y_mm != support
        or fold.end_y_mm != support
        or fold.angle_deg != 90
        or fold.direction != "valley"
        or fold.reachable_face != "front"
    ):
        return False
    topology = {
        "stand-joint-front": ("stand-support", "stand-base"),
        "stand-joint-rear": ("stand-base", "stand-brace"),
        "stand-joint-apex": ("stand-support", "stand-brace"),
    }
    if {j.id: j.part_ids for j in plan.joints} != topology:
        return False
    for operation in plan.operations[3:6]:
        if (
            operation.args.joint_id != operation.id.removesuffix("-attach")
            or operation.args.length_mm != support_part.geometry.width
            or operation.part_ids != topology[operation.args.joint_id]
        ):
            return False
    test = plan.operations[-1].args
    if test.mass_g is None or test.mass_g != plan.constraints.device_mass_g.value:
        return False
    return True


def render_manual(
    plan: m.BuildPlan,
    *,
    process: CutProcess | None = None,
    profile_evidence: tuple[m.Evidence, ...] = (),
    allow_synthetic=False,
) -> Manual:
    """Validate before rendering; unsupported geometry fails closed without panels."""
    result = validate_plan(plan, process=process, allow_synthetic=allow_synthetic)
    if result.status != "accepted":
        return Manual(result.status, (), (), result.blockers)
    if process is not None and any(
        e.project_id != plan.project_id for e in process.evidence
    ):
        return Manual(
            "blocked",
            (),
            (),
            (
                m.Blocker(
                    code="invalid_reference",
                    message="Cutting evidence belongs to another project.",
                ),
            ),
        )
    if not template_valid(plan):
        return Manual(
            "blocked",
            (),
            (),
            (
                m.Blocker(
                    code="unsupported",
                    message="Plan does not match the supported stand geometry, checkpoints and operation sequence.",
                ),
            ),
        )
    plan = result.plan
    if not profile_evidence_valid(
        plan.joint_profiles,
        profile_evidence,
        plan.project_id,
        allow_synthetic=allow_synthetic,
    ):
        return Manual(
            "blocked",
            (),
            (),
            (
                m.Blocker(
                    code="unsupported_profile",
                    message="Resolve measured profile evidence before rendering instructions.",
                ),
            ),
        )
    panels = []
    attached = set()
    used_by_stock: dict[str, float] = {}
    for index, operation in enumerate(plan.operations):
        selected = (
            tuple(p.id for p in plan.parts)
            if operation.type in ("cut_rect", "tape_joint", "functional_test")
            else operation.part_ids
        )
        checkpoints = tuple(
            c for c in plan.checkpoints if c.after_operation_id == operation.id
        )
        instructions = instruction(operation, plan)
        header_extra = max(0, (len(wrap(instructions, width=102)) - 4) * 21)
        checkpoint_y = 740
        checkpoint_rows = sum(
            len(wrap(f"CHECK {c.id}: {c.description}", width=100)) for c in checkpoints
        )
        footer_y = max(830, checkpoint_y + checkpoint_rows * 21 + 30)
        panel_height = footer_y + 70 + header_extra
        root = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"0 0 900 {panel_height}",
                "role": "img",
                "aria-labelledby": "title description",
                "data-operation-id": operation.id,
            },
        )
        text_title = element(root, "title", id="title")
        text_title.text = f"Step {index + 1}: {operation.type} - {operation.id}"
        description = element(root, "desc", id="description")
        description.text = instructions
        element(root, "rect", width=900, height=panel_height, fill="white")
        defs = element(root, "defs")
        marker = element(
            defs,
            "marker",
            id="arrow",
            markerWidth=8,
            markerHeight=8,
            refX=7,
            refY=3,
            orient="auto",
        )
        element(marker, "path", d="M0,0 L0,6 L8,3 z", fill="#111")
        text(
            root,
            35,
            38,
            f"Step {index + 1}/{len(plan.operations)} - {operation.type.replace('_', ' ')}",
            25,
        )
        text(root, 35, 66, operation.id, 15)
        lines(root, 35, 96, instructions, width=102, size=15)
        drawing = element(root, "g", transform=f"translate(0 {header_extra})")
        tape_readout = None
        if operation.type == "tape_joint":
            stock = next(s for s in plan.stocks if s.id == operation.args.stock_id)
            if stock.remaining_length_mm.value is None:
                return Manual(
                    "blocked",
                    (),
                    (),
                    (
                        m.Blocker(
                            code="missing_measurement",
                            message="Tape remaining length unknown.",
                        ),
                    ),
                )
            used_before = used_by_stock.get(stock.id, 0.0)
            this_step = operation.args.length_mm
            remaining_after = stock.remaining_length_mm.value - used_before - this_step
            tape_readout = (stock.id, used_before, this_step, remaining_after)
        if operation.type == "cut_rect":
            flat_view(drawing, plan, operation, selected, stock=True)
        elif (
            operation.type in ("fold", "inspect")
            and operation.id != "stand-inspect-fit"
        ):
            flat_view(drawing, plan, operation, selected)
        else:
            side_view(drawing, plan, operation, attached)
        if tape_readout is not None:
            stock_id, used_before, this_step, remaining_after = tape_readout
            readout = element(drawing, "g", data_stock_id=stock_id)
            text(
                readout, 610, 445, f"tape used before: {dimension(used_before)} mm", 13
            )
            text(readout, 610, 463, f"this step: {dimension(this_step)} mm", 13)
            text(
                readout,
                610,
                481,
                f"tape left after: {dimension(remaining_after)} mm",
                13,
            )
        text(drawing, 35, 645, "Tools: " + ", ".join(tools_for(operation)), 15)
        text(
            drawing,
            35,
            675,
            "Requires user confirmation; this panel records no completion or physical pass.",
            15,
        )
        if allow_synthetic:
            text(
                drawing,
                35,
                705,
                "SYNTHETIC SOFTWARE FIXTURE - not measured stock or a physically verified stand",
                16,
            )
        for checkpoint in checkpoints:
            element(drawing, "g", data_checkpoint_id=checkpoint.id)
            lines(
                drawing,
                35,
                checkpoint_y,
                f"CHECK {checkpoint.id}: {checkpoint.description}",
                width=100,
                size=15,
            )
            checkpoint_y += (
                len(wrap(f"CHECK {checkpoint.id}: {checkpoint.description}", width=100))
                * 21
            )
        lines(
            drawing,
            35,
            footer_y,
            "Expected state: "
            + operation.expected_state_id
            + ". Recheck geometry, joint grip and stability after any revision.",
            width=103,
            size=14,
        )
        svg = ET.tostring(root, encoding="unicode", short_empty_elements=True)
        # dependency_hash covers the visible SVG; version IDs stay excluded
        dependency_hash = sha256(("stand-svg-v1\n" + svg).encode()).hexdigest()
        panels.append(
            Panel(
                operation.id,
                selected,
                tuple(c.id for c in checkpoints),
                dependency_hash,
                svg,
                tools_for(operation),
            )
        )
        attached.update(operation.effects.attached_joint_ids)
        if operation.type == "tape_joint":
            used_by_stock[operation.args.stock_id] = (
                used_by_stock.get(operation.args.stock_id, 0.0)
                + operation.args.length_mm
            )
    bill = tuple(
        BillItem(
            p.id,
            p.source_stock_id,
            1,
            "part",
            f"{number(p.geometry.width)} x {number(p.geometry.height)} mm",
        )
        for p in plan.parts
    )
    for stock in plan.stocks:
        if stock.kind == "tape":
            used = sum(
                o.args.length_mm
                for o in plan.operations
                if o.type == "tape_joint" and o.args.stock_id == stock.id
            )
            bill += (
                BillItem(
                    f"{stock.id}-consumed",
                    stock.id,
                    used,
                    "mm",
                    "Three full-width hinge strips",
                ),
                BillItem(
                    f"{stock.id}-remaining",
                    stock.id,
                    stock.remaining_length_mm.value - used,
                    "mm",
                    "Remaining connector length",
                ),
            )
        if stock.kind == "sheet":
            available = {r.id: r.geometry for r in stock.usable_regions}
            waste = 0.0
            for operation in plan.operations:
                if operation.type != "cut_rect" or operation.args.stock_id != stock.id:
                    continue
                source = available.pop(operation.args.source_region_id)
                children = [
                    p for p in plan.parts if p.id in operation.args.child_part_ids
                ]
                offcuts = operation.effects.created_offcuts
                waste += (
                    source.width * source.height
                    - sum(p.geometry.width * p.geometry.height for p in children)
                    - sum(r.geometry.width * r.geometry.height for r in offcuts)
                )
                available.update({r.id: r.geometry for r in offcuts})
            bill += (
                BillItem(
                    f"{stock.id}-waste",
                    stock.id,
                    waste,
                    "mm2",
                    "Unallocated consumed-source area including kerf/margins; unavailable for reuse",
                ),
                BillItem(
                    f"{stock.id}-remaining",
                    stock.id,
                    sum(r.width * r.height for r in available.values()),
                    "mm2",
                    "Usable stock regions not consumed by planned cuts",
                ),
            )
    return Manual("accepted", tuple(panels), bill, ())
