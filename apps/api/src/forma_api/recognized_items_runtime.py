"""Owner-scoped recognised-item cards (#177 follow-up). No provider call.

Cards hold what an object probably is (a catalog category, "other" or
"uncertain"), where it is in a photo and which saved stock it backs, if any.
They are user-editable proposals: saving them never creates, confirms or
measures stock, and never enables a fabrication operation. The whole list is
replaced on each save, guarded by its own revision and an exact-body receipt.
"""

import json
from uuid import uuid4

from pydantic import Field

from forma_api.projects import Key, ProjectError
from forma_domain.material_catalog import (
    BY_ID,
    CATALOG_VERSION,
    RecognizedInventory,
    RecognizedItem,
    item_label,
)
from forma_domain.models import ID, Blocker, Record, Text

SCOPE = ":recognized-items"


class RecognizedItemsUpdate(Record):
    # None only for the first save of a project.
    expected_revision: ID | None = None
    idempotency_key: Key
    items: tuple[RecognizedItem, ...] = Field(default=(), max_length=64)


class ItemProblem(Record):
    item_id: ID
    problem: Text


class MaterialConflict(Record):
    """A held material: an item contradicted its saved type."""

    # The item still linked to it, if any.
    item_id: ID | None = None
    stock_id: ID
    message: Text


class RecognizedItems(Record):
    project_id: ID
    revision: ID | None
    catalog_version: str = CATALOG_VERSION
    items: tuple[RecognizedItem, ...]
    # Links that no longer hold (photo deleted, stock removed or retyped).
    problems: tuple[ItemProblem, ...] = ()
    # Contradictions that keep the inventory unconfirmed until reconciled.
    conflicts: tuple[MaterialConflict, ...] = ()
    # The saved inventory's confirmation and revision after this save. A
    # change in confirmation issues a new inventory revision.
    inventory_confirmed: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    inventory_revision_id: ID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    replayed: bool = False


def ensure_table(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS recognized_items "
        "(project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE, "
        "revision TEXT NOT NULL, body TEXT NOT NULL)"
    )
    # A saved material an item contradicted, with the type it had then. It
    # stays held, keeping the inventory unconfirmed, until the material is
    # removed, retyped or linked to an item that fits it. Removing or
    # unlinking the item alone does not release it.
    connection.execute(
        "CREATE TABLE IF NOT EXISTS material_holds "
        "(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "stock_id TEXT NOT NULL, kind TEXT NOT NULL, material TEXT NOT NULL, "
        "message TEXT NOT NULL, PRIMARY KEY (project_id, stock_id))"
    )


def _fits(item: RecognizedItem, stock) -> bool:
    info = (
        BY_ID.get(item.identity.category_id)
        if item.identity.outcome == "catalog"
        else None
    )
    return info is not None and (stock.kind, stock.material) == (
        info.stock_kind,
        info.stock_material,
    )


def conflicts(items, stocks) -> tuple[MaterialConflict, ...]:
    """Linked items whose identity contradicts the saved material's type."""

    by_id = {stock.id: stock for stock in stocks}
    found = []
    for item in items:
        stock = by_id.get(item.stock_id) if item.stock_id else None
        if stock is None or _fits(item, stock):
            continue
        what = item_label(item.identity)
        subject = (
            f"This item is identified as {what}"
            if item.name.strip().lower() == what.lower()
            else f"{item.name} is identified as {what}"
        )
        found.append(
            MaterialConflict(
                item_id=item.id,
                stock_id=stock.id,
                message=(
                    f"{subject}, but material "
                    f"{stock.name or stock.id} is saved as {stock.material} "
                    f"{stock.kind}. Remove the material, change its type, or "
                    "change the item back before designing with it."
                )[:500],
            )
        )
    return tuple(found)


def update_holds(connection, project_id, items, stocks) -> tuple[MaterialConflict, ...]:
    """Release resolved holds, add holds for current contradictions, and
    return the holds that remain."""

    ensure_table(connection)
    by_id = {stock.id: stock for stock in stocks}
    for stock_id, kind, material in connection.execute(
        "SELECT stock_id, kind, material FROM material_holds WHERE project_id=?",
        (project_id,),
    ).fetchall():
        stock = by_id.get(stock_id)
        resolved = (
            stock is None
            or (stock.kind, stock.material) != (kind, material)
            or any(i.stock_id == stock_id and _fits(i, stock) for i in items)
        )
        if resolved:
            connection.execute(
                "DELETE FROM material_holds WHERE project_id=? AND stock_id=?",
                (project_id, stock_id),
            )
    for conflict in conflicts(items, stocks):
        stock = by_id[conflict.stock_id]
        connection.execute(
            "INSERT OR REPLACE INTO material_holds VALUES (?, ?, ?, ?, ?)",
            (project_id, stock.id, stock.kind, stock.material, conflict.message),
        )
    return held(connection, project_id, items)


def held(connection, project_id, items) -> tuple[MaterialConflict, ...]:
    ensure_table(connection)
    linked = {i.stock_id: i.id for i in items if i.stock_id}
    return tuple(
        MaterialConflict(
            item_id=linked.get(stock_id),
            stock_id=stock_id,
            message=message
            if stock_id in linked
            else (
                f"Material {stock_id} was identified as something else and is "
                f"still saved as {material} {kind}. Remove it or change its "
                "type before designing with it."
            ),
        )
        for stock_id, kind, material, message in connection.execute(
            "SELECT stock_id, kind, material, message FROM material_holds "
            "WHERE project_id=? ORDER BY stock_id",
            (project_id,),
        ).fetchall()
    )


def hold_blockers(connection, project_id) -> tuple[Blocker, ...]:
    """The project's held materials as report blockers (empty when none).

    A hold withdraws current eligibility only. Saved events, evidence, plan
    versions and repair previews are kept unchanged."""

    found = held(connection, project_id, _stored(connection, project_id)[1])
    if not found:
        return ()
    return (
        Blocker(
            code="needs_confirmation",
            message=(
                "A material in this build was identified as something else. "
                "Reconcile it (correct the item, or remove or retype the "
                "material) before continuing. Earlier records are unchanged."
            ),
            target_ids=tuple(conflict.stock_id for conflict in found),
        ),
    )


def require_no_holds(connection, project_id, action: str) -> None:
    """Refuse a current repair or fabrication action while a material is held.

    Checked inside the action's own transaction, after any exact-body replay
    (a replay returns an earlier, already recorded outcome)."""

    if hold_blockers(connection, project_id):
        raise ProjectError(
            409,
            "blocked",
            f"{action} is paused: a material in this build was identified as "
            "something else. Reconcile it before continuing.",
        )


def inventory_holds(connection, project_id, stocks) -> bool:
    """For an inventory save: True while any material stays held."""

    ensure_table(connection)
    return bool(
        update_holds(connection, project_id, _stored(connection, project_id)[1], stocks)
    )


def _set_confirmed(connection, owner, project, confirmed: bool):
    """Change confirmation under a new inventory revision, so work started
    against the earlier revision is refused as stale when it completes."""
    from uuid import uuid4 as _uuid4

    from forma_api.projects import Project

    updated = Project(
        **{
            **project.model_dump(),
            "inventory_confirmed": confirmed,
            "revision_id": "inventory-" + _uuid4().hex,
        }
    )
    connection.execute(
        "UPDATE projects SET body=? WHERE id=? AND owner=?",
        (updated.model_dump_json(), project.id, owner),
    )
    return updated


def reconcile_confirmation(connection, owner, project, items):
    """Withdraw confirmation while a material is held; restore it when the
    last hold is released. Never confirms an inventory the user did not
    save: without holds, an unconfirmed inventory stays unconfirmed."""

    had = bool(held(connection, project.id, items))
    remaining = update_holds(connection, project.id, items, project.stocks)
    if remaining and project.inventory_confirmed:
        return _set_confirmed(connection, owner, project, False)
    if had and not remaining and not project.inventory_confirmed:
        return _set_confirmed(connection, owner, project, True)
    return project


def _stored(connection, project_id):
    row = connection.execute(
        "SELECT revision, body FROM recognized_items WHERE project_id=?",
        (project_id,),
    ).fetchone()
    if row is None:
        return None, ()
    return row[0], RecognizedInventory.model_validate_json(row[1]).items


def _media_ids(connection, project_id) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT id FROM media WHERE project_id=?", (project_id,)
        )
    }


def problems(connection, project, items) -> tuple[ItemProblem, ...]:
    media = _media_ids(connection, project.id)
    stocks = {stock.id: stock for stock in project.stocks}
    found = []
    for item in items:
        if item.media_id and item.media_id not in media:
            found.append(ItemProblem(item_id=item.id, problem="The photo was deleted."))
        if item.stock_id is None:
            continue
        stock = stocks.get(item.stock_id)
        if stock is None:
            found.append(
                ItemProblem(
                    item_id=item.id,
                    problem="The linked material is no longer in the saved inventory.",
                )
            )
            continue
        info = (
            BY_ID.get(item.identity.category_id)
            if item.identity.outcome == "catalog"
            else None
        )
        if info is None or (stock.kind, stock.material) != (
            info.stock_kind,
            info.stock_material,
        ):
            found.append(
                ItemProblem(
                    item_id=item.id,
                    problem="The linked material no longer matches what this item is.",
                )
            )
    return tuple(found)


def _validate(connection, project, items, kept: set[tuple[str, str]]) -> None:
    """``kept`` holds (item, stock) links already saved: a correction may keep
    one that no longer fits, reported as a problem until resolved. A new link
    must fit."""
    RecognizedInventory(items=items)  # unique IDs, one item per stock
    media = _media_ids(connection, project.id)
    stocks = {stock.id: stock for stock in project.stocks}
    for item in items:
        if item.media_id and item.media_id not in media:
            raise ProjectError(404, "not_found", f"Photo for {item.name} not found")
        if item.stock_id is None:
            continue
        stock = stocks.get(item.stock_id)
        if stock is None:
            raise ProjectError(
                422, "validation_error", f"{item.name}: save the linked material first"
            )
        if (item.id, item.stock_id) in kept:
            continue
        info = (
            BY_ID.get(item.identity.category_id)
            if item.identity.outcome == "catalog"
            else None
        )
        if info is None or info.support != "build_rules_available":
            # Recognised inventory stays available without enabling operations.
            raise ProjectError(
                422,
                "validation_error",
                f"{item.name}: build rules are not available for this item yet",
            )
        if (stock.kind, stock.material) != (info.stock_kind, info.stock_material):
            raise ProjectError(
                422,
                "validation_error",
                f"{item.name}: the linked material has another type",
            )


def read(store, owner: str, project_id: str) -> RecognizedItems:
    with store.transaction() as connection:
        ensure_table(connection)
        project = store.read(connection, owner, project_id)
        revision, items = _stored(connection, project_id)
        return RecognizedItems(
            project_id=project_id,
            revision=revision,
            items=items,
            problems=problems(connection, project, items),
            conflicts=held(connection, project_id, items),
            inventory_confirmed=project.inventory_confirmed,
            inventory_revision_id=project.revision_id,
        )


def save(store, owner: str, project_id: str, body: RecognizedItemsUpdate):
    scope = project_id + SCOPE
    with store.transaction() as connection:
        ensure_table(connection)
        project = store.read(connection, owner, project_id)
        digest, replay = store.replay(
            connection, owner, scope, body.idempotency_key, body.model_dump(mode="json")
        )
        if replay:
            return RecognizedItems.model_validate({**replay, "replayed": True})
        revision, previous = _stored(connection, project_id)
        if revision != body.expected_revision:
            raise ProjectError(
                409, "stale_version", "Items changed elsewhere; reload them"
            )
        try:
            kept = {(i.id, i.stock_id) for i in previous if i.stock_id}
            _validate(connection, project, body.items, kept)
        except ValueError as exc:
            raise ProjectError(422, "validation_error", str(exc)[:200]) from None
        before = {(c.item_id, c.stock_id) for c in conflicts(previous, project.stocks)}
        found = conflicts(body.items, project.stocks)
        if project.active_version_id is not None and any(
            (c.item_id, c.stock_id) not in before for c in found
        ):
            raise ProjectError(
                409,
                "blocked",
                "A build is active with this material. Finish or stop the build "
                "before identifying its item as something else.",
            )
        new_revision = "items-" + uuid4().hex
        document = RecognizedInventory(items=body.items).model_dump_json()
        connection.execute(
            "INSERT INTO recognized_items VALUES (?, ?, ?) ON CONFLICT(project_id) "
            "DO UPDATE SET revision=excluded.revision, body=excluded.body",
            (project_id, new_revision, document),
        )
        project = reconcile_confirmation(connection, owner, project, body.items)
        result = RecognizedItems(
            project_id=project_id,
            revision=new_revision,
            items=body.items,
            problems=problems(connection, project, body.items),
            conflicts=held(connection, project_id, body.items),
            inventory_confirmed=project.inventory_confirmed,
            inventory_revision_id=project.revision_id,
        )
        store.remember(
            connection,
            owner,
            scope,
            body.idempotency_key,
            digest,
            json.loads(result.model_dump_json()),
        )
        return result


def reconcile_existing(store) -> int:
    """Once at startup: contradictions saved before reconciliation existed
    are held like new ones, active builds included. Their physical history,
    previews and plan versions are untouched; repair and fabrication actions
    for the build are paused while the hold remains (``require_no_holds``).
    Returns how many projects were held."""

    from forma_api.projects import Project

    count = 0
    with store.transaction() as connection:
        ensure_table(connection)
        rows = connection.execute(
            "SELECT p.owner, p.body, r.body FROM recognized_items r "
            "JOIN projects p ON p.id = r.project_id"
        ).fetchall()
        for owner, project_body, items_body in rows:
            project = Project.model_validate_json(project_body)
            items = RecognizedInventory.model_validate_json(items_body).items
            if conflicts(items, project.stocks):
                reconcile_confirmation(connection, owner, project, items)
                count += 1
    return count


def purge(connection, owner: str, project_id: str) -> None:
    ensure_table(connection)
    connection.execute("DELETE FROM recognized_items WHERE project_id=?", (project_id,))
    connection.execute("DELETE FROM material_holds WHERE project_id=?", (project_id,))
    connection.execute(
        "DELETE FROM requests WHERE owner=? AND scope=?", (owner, project_id + SCOPE)
    )
