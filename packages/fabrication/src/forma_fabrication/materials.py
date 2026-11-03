"""Validate a current projection against immutable sources and actual cuts/use."""

from decimal import Decimal

from forma_domain.fabrication_contracts import FabricationInput
from forma_domain.models import Blocker


def projection_blockers(data: FabricationInput) -> tuple[Blocker, ...]:
    blockers = []

    def fail(code, message, *ids):
        blockers.append(Blocker(code=code, message=message, target_ids=ids))

    originals, known_regions, created, consumed, spent = {}, {}, set(), set(), {}
    seen_events = set()
    for history in data.lineage:
        for stock in history.plan.stocks:
            originals.setdefault(stock.id, stock)
            for region in stock.usable_regions:
                known_regions.setdefault(region.id, (stock.id, region.geometry))
        operations = {op.id: op for op in history.plan.operations}
        for op in history.plan.operations:
            if op.type == "cut_rect":
                for region in op.effects.created_offcuts:
                    value = (op.args.stock_id, region.geometry)
                    if region.id in known_regions and known_regions[region.id] != value:
                        fail(
                            "invalid_reference",
                            "Offcut identity or geometry changed.",
                            region.id,
                        )
                    known_regions[region.id] = value
        for event in history.events:
            if event.kind != "operation_confirmed" or event.id in seen_events:
                continue
            seen_events.add(event.id)
            op = operations.get(event.operation_id)
            if op is None:
                continue
            if op.type == "cut_rect":
                consumed.add(op.args.source_region_id)
                created.update(r.id for r in op.effects.created_offcuts)
            elif op.type in {"tape_joint", "tie_joint"}:
                sid = op.args.stock_id
                spent[sid] = spent.get(sid, Decimal(0)) + Decimal(
                    str(op.args.length_mm)
                )

    current_ids = [s.id for s in data.remaining_stock]
    if len(set(current_ids)) != len(current_ids) or set(current_ids) != set(originals):
        fail(
            "invalid_reference",
            "Remaining stock must contain exactly the known physical sources.",
        )
    # Original regions are available without a cut; offcuts require actual work.
    original_regions = {r.id for s in originals.values() for r in s.usable_regions}
    seen_regions = set()
    for stock in data.remaining_stock:
        original = originals.get(stock.id)
        if original is not None and any(
            getattr(stock, name) != getattr(original, name)
            for name in ("kind", "material", "width_mm", "height_mm", "thickness_mm")
        ):
            fail(
                "invalid_reference",
                "Remaining stock identity or measurements changed.",
                stock.id,
            )
        for region in stock.usable_regions:
            if region.id in seen_regions or known_regions.get(region.id) != (
                stock.id,
                region.geometry,
            ):
                fail(
                    "invalid_reference",
                    "Remaining region identity or geometry conflicts with history.",
                    stock.id,
                    region.id,
                )
            seen_regions.add(region.id)
            if region.id in consumed:
                fail(
                    "stock_exhausted",
                    "A consumed parent region cannot return to remaining stock.",
                    region.id,
                )
            if region.id not in original_regions and region.id not in created:
                fail(
                    "invalid_order",
                    "A remaining offcut requires its actual confirmed source cut.",
                    region.id,
                )
        if stock.kind in {"tape", "cord"} and original is not None:
            initial, balance = (
                original.remaining_length_mm.value,
                stock.remaining_length_mm.value,
            )
            if (
                initial is not None
                and Decimal(str(initial)) - spent.get(stock.id, Decimal(0)) < 0
            ):
                fail(
                    "stock_exhausted",
                    "Confirmed connector use exceeds its known starting balance.",
                    stock.id,
                )
            if (
                initial is not None
                and balance is not None
                and Decimal(str(balance))
                > Decimal(str(initial)) - spent.get(stock.id, Decimal(0))
            ):
                fail(
                    "stock_exhausted",
                    "Remaining connector stock refunds confirmed consumption.",
                    stock.id,
                )
    return tuple(blockers)
