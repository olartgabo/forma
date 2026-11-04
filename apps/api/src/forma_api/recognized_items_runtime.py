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


class RecognizedItems(Record):
    project_id: ID
    revision: ID | None
    catalog_version: str = CATALOG_VERSION
    items: tuple[RecognizedItem, ...]
    # Links that no longer hold (photo deleted, stock removed or retyped).
    problems: tuple[ItemProblem, ...] = ()
    replayed: bool = False


def ensure_table(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS recognized_items "
        "(project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE, "
        "revision TEXT NOT NULL, body TEXT NOT NULL)"
    )


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
        new_revision = "items-" + uuid4().hex
        document = RecognizedInventory(items=body.items).model_dump_json()
        connection.execute(
            "INSERT INTO recognized_items VALUES (?, ?, ?) ON CONFLICT(project_id) "
            "DO UPDATE SET revision=excluded.revision, body=excluded.body",
            (project_id, new_revision, document),
        )
        result = RecognizedItems(
            project_id=project_id,
            revision=new_revision,
            items=body.items,
            problems=problems(connection, project, body.items),
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


def purge(connection, owner: str, project_id: str) -> None:
    ensure_table(connection)
    connection.execute("DELETE FROM recognized_items WHERE project_id=?", (project_id,))
    connection.execute(
        "DELETE FROM requests WHERE owner=? AND scope=?", (owner, project_id + SCOPE)
    )
