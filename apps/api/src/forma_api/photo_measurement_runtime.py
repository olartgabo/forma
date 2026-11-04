"""Owner-scoped photo estimates (#177). Local and deterministic; no provider call.

An estimate is stored with everything it depends on. It becomes stale, never
deleted, when its photo, stock identity or replacement estimate changes. The
inventory accepts a ``photo_estimate`` value only when it equals a current
estimate's displayed value for that stock and field; it is never confirmed.
"""

import hashlib
import json
import threading
from typing import Literal
from uuid import uuid4

import cv2
import numpy as np
from forma_photo_measure import card_svg
from forma_photo_measure import estimate as run_estimate

from forma_api.projects import Key, ProjectError
from forma_domain.models import ID, Record, Stock, Text
from forma_domain.photo_measurement_contracts import (
    CaptureDeclaration,
    EstimateInput,
    OutlineInput,
    PhotoEstimate,
    ReferenceInput,
)

SCOPE = ":photo-estimate"
# Two concurrent estimates at most; each holds one decoded photo (<= 20 MP).
_SLOTS = threading.BoundedSemaphore(2)
SUPPORTED_TYPES = ("image/jpeg", "image/png", "image/webp")


class PhotoEstimateRequest(Record):
    media_id: ID
    expected_revision_id: ID
    idempotency_key: Key
    stock_id: ID
    stock_kind: Literal["sheet", "strip", "tape", "cord"]
    stock_material: Literal["cardboard", "paperboard", "other_supported"]
    reference: ReferenceInput
    outline: OutlineInput
    capture: CaptureDeclaration


class PhotoEstimateRecord(Record):
    estimate_id: ID
    project_id: ID
    created_revision_id: ID
    estimate: PhotoEstimate
    # Why a saved inventory change permanently invalidated this estimate.
    retired: Text | None = None
    status: Literal["current", "stale"] = "current"
    stale_reasons: tuple[Text, ...] = ()
    replayed: bool = False


class PhotoEstimateList(Record):
    records: tuple[PhotoEstimateRecord, ...]


def ensure_table(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS photo_estimates "
        "(id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
        "REFERENCES projects(id) ON DELETE CASCADE, "
        "stock_id TEXT NOT NULL, body TEXT NOT NULL)"
    )


def create(store, owner: str, project_id: str, body: PhotoEstimateRequest):
    scope = project_id + SCOPE
    with store.transaction() as connection:
        ensure_table(connection)
        project = store.read(connection, owner, project_id)
        digest, replay = store.replay(
            connection, owner, scope, body.idempotency_key, body.model_dump(mode="json")
        )
        if replay:
            return _record(json.dumps(replay))
        if project.revision_id != body.expected_revision_id:
            raise ProjectError(409, "stale_version", "Inventory changed; reload it")
        row = connection.execute(
            "SELECT content_type, width_px, height_px, body FROM media WHERE id=? AND project_id=?",
            (body.media_id, project_id),
        ).fetchone()
        if row is None:
            raise ProjectError(404, "not_found", "Photo not found")
        content_type, width, height, data = row[0], row[1], row[2], bytes(row[3])
    if content_type not in SUPPORTED_TYPES:
        raise ProjectError(422, "validation_error", "Unsupported photo type")
    data_input = EstimateInput(
        stock_id=body.stock_id,
        stock_kind=body.stock_kind,
        stock_material=body.stock_material,
        media_id=body.media_id,
        media_sha256=hashlib.sha256(data).hexdigest(),
        image_width_px=width,
        image_height_px=height,
        reference=body.reference,
        outline=body.outline,
        capture=body.capture,
    )
    if not _SLOTS.acquire(blocking=False):
        raise ProjectError(429, "blocked", "Photo measurement is busy; retry shortly")
    try:
        image = cv2.imdecode(
            np.frombuffer(data, np.uint8),
            cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION,
        )
        if image is None or image.shape[:2] != (height, width):
            raise ProjectError(
                422, "validation_error", "Stored photo could not be decoded"
            )
        try:
            result = run_estimate(image, data_input)
        except ValueError as exc:
            raise ProjectError(422, "validation_error", str(exc)[:200]) from None
    finally:
        _SLOTS.release()
    with store.transaction() as connection:
        ensure_table(connection)
        # An exact retry that raced this one returns the first stored result.
        digest, replay = store.replay(
            connection, owner, scope, body.idempotency_key, body.model_dump(mode="json")
        )
        if replay:
            return _record(json.dumps(replay))
        current = store.read(connection, owner, project_id)
        if current.revision_id != body.expected_revision_id:
            raise ProjectError(
                409, "stale_version", "Inventory changed during measurement; reload it"
            )
        record = PhotoEstimateRecord(
            estimate_id="estimate-" + uuid4().hex,
            project_id=project_id,
            created_revision_id=body.expected_revision_id,
            estimate=result,
        )
        connection.execute(
            "INSERT INTO photo_estimates VALUES (?, ?, ?, ?)",
            (record.estimate_id, project_id, body.stock_id, record.model_dump_json()),
        )
        response = record.model_dump(mode="json")
        store.remember(connection, owner, scope, body.idempotency_key, digest, response)
        return response


def _records(connection, project_id) -> list[PhotoEstimateRecord]:
    ensure_table(connection)
    rows = connection.execute(
        "SELECT body FROM photo_estimates WHERE project_id=? ORDER BY rowid",
        (project_id,),
    ).fetchall()
    return [_record(r[0]) for r in rows]


def _record(body: str) -> PhotoEstimateRecord:
    data = json.loads(body)
    # Unpublished development builds of #177 stored a boolean `removed`.
    if "removed" in data:
        removed = data.pop("removed")
        if removed and not data.get("retired"):
            data["retired"] = "The material was removed from the saved inventory."
    return PhotoEstimateRecord.model_validate(data)


def assess(connection, project, stocks: tuple[Stock, ...] | None = None):
    """All records with current/stale status against the given (or saved) stock."""

    stocks = project.stocks if stocks is None else stocks
    by_id = {s.id: s for s in stocks}
    records = _records(connection, project.id)
    latest = {}
    for record in records:
        # Only a usable estimate replaces an earlier one; a failed retry does not.
        if record.estimate.dimensions:
            latest[record.estimate.input.stock_id] = record.estimate_id
    result = []
    for record in records:
        data = record.estimate.input
        reasons = []
        media = connection.execute(
            "SELECT body FROM media WHERE id=? AND project_id=?",
            (data.media_id, project.id),
        ).fetchone()
        if media is None:
            reasons.append("The photo was deleted.")
        elif hashlib.sha256(bytes(media[0])).hexdigest() != data.media_sha256:
            reasons.append("The photo changed.")
        stock = by_id.get(data.stock_id)
        if stock is not None and (stock.kind, stock.material) != (
            data.stock_kind,
            data.stock_material,
        ):
            reasons.append("The material type changed.")
        if record.retired:
            reasons.append(record.retired)
        elif (
            stock is None
            and project.revision_id != record.created_revision_id
            and project.inventory_confirmed
        ):
            reasons.append("The material is no longer in the saved inventory.")
        if latest.get(data.stock_id, record.estimate_id) != record.estimate_id:
            reasons.append("A newer estimate replaced this one.")
        result.append(
            record.model_copy(
                update={
                    "status": "stale" if reasons else "current",
                    "stale_reasons": tuple(reasons),
                }
            )
        )
    return result


def list_records(store, owner: str, project_id: str) -> PhotoEstimateList:
    with store.transaction() as connection:
        project = store.read(connection, owner, project_id)
        return PhotoEstimateList(records=tuple(assess(connection, project)))


def inventory_problems(connection, project, stocks: tuple[Stock, ...]) -> list[str]:
    """Photo-estimate values must match a current estimate; never confirmed."""

    needed = [
        (stock, name, getattr(stock, name).value)
        for stock in stocks
        for name in ("width_mm", "height_mm", "thickness_mm", "remaining_length_mm")
        if getattr(stock, name).source == "photo_estimate"
    ]
    if not needed:
        return []
    current = [r for r in assess(connection, project, stocks) if r.status == "current"]
    problems = []
    for stock, name, value in needed:
        match = any(
            r.estimate.input.stock_id == stock.id
            and r.estimate.input.media_id in stock.image_ids
            and any(
                d.stock_field == name and abs(d.display_value - value) < 1e-6
                for d in r.estimate.dimensions
            )
            for r in current
        )
        if not match:
            problems.append(f"{stock.id} {name}")
    return problems


def retire_changed(connection, project_id: str, stocks: tuple[Stock, ...]) -> None:
    """After an inventory save, permanently retire estimates whose stock was
    removed, changed type or material, or no longer links the source photo.
    Restoring the old values later cannot make them current again."""

    by_id = {stock.id: stock for stock in stocks}
    for record in _records(connection, project_id):
        data = record.estimate.input
        stock = by_id.get(data.stock_id)
        if record.retired:
            continue
        if stock is None:
            reason = "The material was removed from the saved inventory."
        elif (stock.kind, stock.material) != (data.stock_kind, data.stock_material):
            reason = "The material type changed."
        elif data.media_id not in stock.image_ids:
            reason = "The photo is no longer linked to this material."
        else:
            continue
        connection.execute(
            "UPDATE photo_estimates SET body=? WHERE id=?",
            (
                record.model_copy(update={"retired": reason}).model_dump_json(),
                record.estimate_id,
            ),
        )


def purge(connection, owner: str, project_id: str) -> None:
    ensure_table(connection)
    connection.execute("DELETE FROM photo_estimates WHERE project_id=?", (project_id,))
    connection.execute(
        "DELETE FROM requests WHERE owner=? AND scope=?", (owner, project_id + SCOPE)
    )


def card_payload() -> bytes:
    return card_svg().encode()
