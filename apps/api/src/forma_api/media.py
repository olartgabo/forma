"""Private decoded photos; uploads confer no provider consent or physical evidence."""

import hashlib
import warnings
from io import BytesIO
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from forma_api.projects import Key, ProjectError, ProjectStore
from forma_domain.models import ID, Record

MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 20_000_000
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class Media(Record):
    id: ID
    project_id: ID
    content_type: str
    byte_count: int
    width_px: int
    height_px: int


class MediaResult(Record):
    media: Media
    replayed: bool = False


class MediaList(Record):
    media: tuple[Media, ...]


class MediaDeleteResult(Record):
    media_id: ID
    deleted: bool = True
    replayed: bool = False


def decode_photo(body: bytes, content_type: str) -> tuple[bytes, int, int]:
    if not body or len(body) > MAX_PHOTO_BYTES:
        raise ProjectError(
            413, "validation_error", "Photo must contain 1 to 8388608 bytes"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body), formats=list(FORMATS.values())) as image:
                if image.format != FORMATS[content_type]:
                    raise ProjectError(
                        415,
                        "validation_error",
                        "Photo MIME type does not match its content",
                    )
                if image.width * image.height > MAX_PHOTO_PIXELS:
                    raise ProjectError(
                        413, "validation_error", "Photo exceeds 20000000 decoded pixels"
                    )
                if getattr(image, "is_animated", False):
                    raise ProjectError(
                        422, "validation_error", "Animated photos are not supported"
                    )
                image.verify()
            with Image.open(BytesIO(body), formats=[FORMATS[content_type]]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
                if oriented.mode == "P" and "transparency" in oriented.info:
                    mode = "RGBA"
                converted = oriented.convert(mode)
                # A fresh image carries pixels only: no EXIF, ICC or PNG text.
                with Image.frombytes(
                    mode, converted.size, converted.tobytes()
                ) as clean:
                    output = BytesIO()
                    clean.save(output, format=FORMATS[content_type])
                    normalized = output.getvalue()
                    width, height = clean.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ProjectError(
            413, "validation_error", "Photo exceeds decoded pixel limits"
        ) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ProjectError(
            422, "validation_error", "Photo could not be decoded"
        ) from None
    if len(normalized) > MAX_PHOTO_BYTES:
        raise ProjectError(
            413, "validation_error", "Normalized photo exceeds 8388608 bytes"
        )
    return normalized, width, height


def media_router(store: ProjectStore, authenticate) -> APIRouter:
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(prefix="/{project_id}/media", tags=["private media"])

    def require_project(owner, project_id):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)

    def save(owner, project_id, key, body, content_type):
        normalized, width, height = decode_photo(body, content_type)
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            scope = project_id + ":media:upload"
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                key,
                {
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "content_type": content_type,
                },
            )
            if replay:
                row = connection.execute(
                    "SELECT id FROM media WHERE id=? AND project_id=?",
                    (replay["media"]["id"], project_id),
                ).fetchone()
                if row is None:
                    raise ProjectError(404, "not_found", "Photo was deleted")
                return replay
            media = Media(
                id="media-" + uuid4().hex,
                project_id=project_id,
                content_type=content_type,
                byte_count=len(normalized),
                width_px=width,
                height_px=height,
            )
            connection.execute(
                "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?)",
                (media.id, project_id, content_type, width, height, normalized),
            )
            result = MediaResult(media=media).model_dump(mode="json")
            store.remember(connection, owner, scope, key, digest, result)
            return result

    @router.post("", response_model=MediaResult, status_code=201)
    async def upload(
        project_id: ID,
        request: Request,
        owner: Owner,
        idempotency_key: Annotated[Key, Header()],
    ):
        await run_in_threadpool(require_project, owner, project_id)
        content_type = (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if (
            content_type not in FORMATS
            or request.headers.get("content-encoding", "identity") != "identity"
        ):
            raise ProjectError(
                415, "validation_error", "Upload a JPEG, PNG or WebP photo"
            )
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                raise ProjectError(
                    400, "validation_error", "Invalid Content-Length"
                ) from None
            if length < 0 or length > MAX_PHOTO_BYTES:
                raise ProjectError(
                    413, "validation_error", "Photo exceeds 8388608 bytes"
                )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_PHOTO_BYTES:
                raise ProjectError(
                    413, "validation_error", "Photo exceeds 8388608 bytes"
                )
            body.extend(chunk)
        return await run_in_threadpool(
            save, owner, project_id, idempotency_key, bytes(body), content_type
        )

    @router.get("", response_model=MediaList)
    def list_media(project_id: ID, owner: Owner, response: Response):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            rows = connection.execute(
                "SELECT id, content_type, width_px, height_px, length(body) "
                "FROM media WHERE project_id=? ORDER BY rowid",
                (project_id,),
            ).fetchall()
        response.headers["Cache-Control"] = "private, no-store"
        return MediaList(
            media=tuple(
                Media(
                    id=row[0],
                    project_id=project_id,
                    content_type=row[1],
                    width_px=row[2],
                    height_px=row[3],
                    byte_count=row[4],
                )
                for row in rows
            )
        )

    @router.get("/{media_id}")
    def get(project_id: ID, media_id: ID, owner: Owner):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)
            row = connection.execute(
                "SELECT content_type, body FROM media WHERE id=? AND project_id=?",
                (media_id, project_id),
            ).fetchone()
            if row is None:
                raise ProjectError(404, "not_found", "Photo not found")
        return Response(
            content=row[1],
            media_type=row[0],
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment",
            },
        )

    @router.delete("/{media_id}", response_model=MediaDeleteResult)
    def delete(
        project_id: ID,
        media_id: ID,
        owner: Owner,
        idempotency_key: Annotated[Key, Header()],
    ):
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":media:delete:" + media_id
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                idempotency_key,
                {"media_id": media_id},
            )
            if replay:
                return replay
            if (
                connection.execute(
                    "SELECT id FROM media WHERE id=? AND project_id=?",
                    (media_id, project_id),
                ).fetchone()
                is None
            ):
                raise ProjectError(404, "not_found", "Photo not found")
            if any(media_id in stock.image_ids for stock in project.stocks):
                raise ProjectError(
                    409,
                    "blocked",
                    "Remove this photo from inventory before deleting it",
                )
            connection.execute(
                "DELETE FROM media WHERE id=? AND project_id=?", (media_id, project_id)
            )
            result = MediaDeleteResult(media_id=media_id).model_dump(mode="json")
            store.remember(connection, owner, scope, idempotency_key, digest, result)
            return result

    return router
