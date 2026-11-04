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
from forma_domain.models import ID, Record, Text

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
    """A saved material contradicted by what its linked item was identified as."""

    item_id: ID
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
    # A project whose confirmed inventory was withdrawn because an item
    # contradicts a saved material. Cleared when the contradiction is gone.
    connection.execute(
        "CREATE TABLE IF NOT EXISTS inventory_holds "
        "(project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE)"
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


def stored_conflicts(connection, project_id, stocks) -> tuple[MaterialConflict, ...]:
    ensure_table(connection)
    return conflicts(_stored(connection, project_id)[1], stocks)


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
    """Withdraw confirmation while a contradiction exists; restore it when a
    hold placed for that reason is no longer needed. Never confirms an
    inventory the user did not save."""

    held = (
        connection.execute(
            "SELECT 1 FROM inventory_holds WHERE project_id=?", (project.id,)
        ).fetchone()
        is not None
    )
    if conflicts(items, project.stocks):
        if project.inventory_confirmed:
            connection.execute(
                "INSERT OR IGNORE INTO inventory_holds VALUES (?)", (project.id,)
            )
            return _set_confirmed(connection, owner, project, False)
        return project
    if held:
        connection.execute(
            "DELETE FROM inventory_holds WHERE project_id=?", (project.id,)
        )
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
            conflicts=conflicts(items, project.stocks),
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
            conflicts=found,
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
    withdraw confirmation like new ones. Active builds are left unchanged
    (their inventory cannot change until the build ends); new contradictions
    are refused during a build. Returns how many projects were held."""

    from forma_api.projects import Project

    held = 0
    with store.transaction() as connection:
        ensure_table(connection)
        rows = connection.execute(
            "SELECT p.owner, p.body, r.body FROM recognized_items r "
            "JOIN projects p ON p.id = r.project_id"
        ).fetchall()
        for owner, project_body, items_body in rows:
            project = Project.model_validate_json(project_body)
            if project.active_version_id is not None or not project.inventory_confirmed:
                continue
            items = RecognizedInventory.model_validate_json(items_body).items
            if conflicts(items, project.stocks):
                reconcile_confirmation(connection, owner, project, items)
                held += 1
    return held


def purge(connection, owner: str, project_id: str) -> None:
    ensure_table(connection)
    connection.execute("DELETE FROM recognized_items WHERE project_id=?", (project_id,))
    connection.execute("DELETE FROM inventory_holds WHERE project_id=?", (project_id,))
    connection.execute(
        "DELETE FROM requests WHERE owner=? AND scope=?", (owner, project_id + SCOPE)
    )
