"""Local private project persistence; never activates plans or records physical work."""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, StringConstraints, model_validator

from forma_domain.models import ID, Constraints, ErrorEnvelope, Record, Stock, Text

Key = Annotated[str, Field(min_length=8, max_length=128)]


class CreateProject(Record):
    goal: Text
    idempotency_key: Key


class BuildRequirements(Record):
    tools: tuple[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
        ],
        ...,
    ] = Field(max_length=32)
    device_description: Text | None = None
    constraints: Constraints

    @model_validator(mode="after")
    def confirmed_inputs(self):
        if len({tool.casefold() for tool in self.tools}) != len(self.tools):
            raise ValueError("duplicate tool names")
        if self.constraints.allowed_profile_ids:
            raise ValueError("profile selection requires a trusted catalogue")
        for name in (
            "device_mass_g",
            "support_angle_deg",
            "max_footprint_width_mm",
            "max_footprint_height_mm",
        ):
            measurement = getattr(self.constraints, name)
            if measurement.evidence_ids:
                raise ValueError("unresolved measurement evidence")
            if measurement.value is not None and (
                not measurement.confirmed
                or measurement.value <= 0
                or (name == "support_angle_deg" and measurement.value >= 90)
            ):
                raise ValueError("known requirements need positive confirmed values")
        return self


class InventoryUpdate(Record):
    expected_revision_id: ID
    idempotency_key: Key
    stocks: tuple[Stock, ...] = Field(min_length=1, max_length=32)
    user_confirmed: Literal[True]
    requirements: BuildRequirements | None = None


class Project(Record):
    id: ID
    goal: Text
    revision_id: ID
    active_version_id: ID | None = None
    stocks: tuple[Stock, ...] = ()
    inventory_confirmed: bool = False
    requirements: BuildRequirements | None = None


class ProjectResult(Record):
    project: Project
    replayed: bool = False


class DeleteResult(Record):
    project_id: ID
    deleted: Literal[True] = True
    replayed: bool = False


class ProjectError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.envelope = ErrorEnvelope(code=code, message=message)


async def project_error_handler(request: Request, exc: ProjectError):
    return JSONResponse(exc.envelope.model_dump(mode="json"), status_code=exc.status)


class ProjectStore:
    def __init__(self, directory: Path):
        self.directory = directory

    @contextmanager
    def transaction(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.directory / "projects.sqlite3", timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS projects "
                "(id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests "
                "(owner TEXT, scope TEXT, key TEXT, digest TEXT NOT NULL, "
                "response TEXT NOT NULL, PRIMARY KEY(owner, scope, key))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS media "
                "(id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
                "REFERENCES projects(id) ON DELETE CASCADE, "
                "content_type TEXT NOT NULL, width_px INTEGER NOT NULL, "
                "height_px INTEGER NOT NULL, body BLOB NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS plans "
                "(version_id TEXT PRIMARY KEY, project_id TEXT NOT NULL "
                "REFERENCES projects(id) ON DELETE CASCADE, "
                "inventory_revision_id TEXT NOT NULL, body TEXT NOT NULL, "
                "process TEXT NOT NULL, parameters TEXT NOT NULL)"
            )
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def read(connection, owner: str, project_id: str) -> Project:
        row = connection.execute(
            "SELECT body FROM projects WHERE id = ? AND owner = ?", (project_id, owner)
        ).fetchone()
        if row is None:
            raise ProjectError(404, "not_found", "Project not found")
        return Project.model_validate_json(row[0])

    @staticmethod
    def replay(connection, owner, scope, key, payload):
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row = connection.execute(
            "SELECT digest, response FROM requests WHERE owner=? AND scope=? AND key=?",
            (owner, scope, key),
        ).fetchone()
        if row is not None:
            if row[0] != digest:
                raise ProjectError(
                    409, "idempotency_conflict", "Key already used for another request"
                )
            return digest, {**json.loads(row[1]), "replayed": True}
        return digest, None

    @staticmethod
    def remember(connection, owner, scope, key, digest, response):
        connection.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
            (owner, scope, key, digest, json.dumps(response)),
        )


def project_router(store: ProjectStore, credentials: dict[str, str]) -> APIRouter:
    if any(len(token) < 32 for token in credentials.values()) or len(
        set(credentials.values())
    ) != len(credentials):
        raise ValueError(
            "Owner credentials must be distinct and at least 32 characters"
        )
    # Keep only digests in the dependency closure; never expose tokens in responses.
    owners = {
        hashlib.sha256(token.encode()).digest(): owner
        for owner, token in credentials.items()
    }
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        supplied: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        if supplied is not None:
            digest = hashlib.sha256(supplied.credentials.encode()).digest()
            for candidate, owner in owners.items():
                if secrets.compare_digest(digest, candidate):
                    return owner
        raise ProjectError(
            401, "forbidden", "A configured bearer credential is required"
        )

    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.post("", response_model=ProjectResult, status_code=201)
    def create(body: CreateProject, owner: Owner):
        with store.transaction() as connection:
            digest, replay = store.replay(
                connection, owner, "create", body.idempotency_key, body.model_dump()
            )
            if replay:
                if "deleted_project_id" in replay:
                    raise ProjectError(404, "not_found", "Project was deleted")
                # Creation retries must not resurrect deleted projects or their data.
                store.read(connection, owner, replay["project"]["id"])
                return replay
            project = Project(
                id="project-" + uuid4().hex,
                goal=body.goal,
                revision_id="inventory-" + uuid4().hex,
            )
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?)",
                (project.id, owner, project.model_dump_json()),
            )
            result = ProjectResult(project=project).model_dump(mode="json")
            store.remember(
                connection, owner, "create", body.idempotency_key, digest, result
            )
            return result

    @router.get("/{project_id}", response_model=Project)
    def get(project_id: ID, owner: Owner):
        with store.transaction() as connection:
            return store.read(connection, owner, project_id)

    @router.put("/{project_id}/inventory", response_model=ProjectResult)
    def inventory(project_id: ID, body: InventoryUpdate, owner: Owner):
        with store.transaction() as connection:
            project = store.read(connection, owner, project_id)
            scope = project_id + ":inventory"
            digest, replay = store.replay(
                connection,
                owner,
                scope,
                body.idempotency_key,
                body.model_dump(
                    mode="json",
                    exclude={"requirements"}
                    if "requirements" not in body.model_fields_set
                    else set(),
                ),
            )
            if replay:
                return replay
            if project.revision_id != body.expected_revision_id:
                raise ProjectError(409, "stale_version", "Inventory changed; reload it")
            if project.active_version_id is not None:
                raise ProjectError(409, "blocked", "Active plans require a revision")
            if len({stock.id for stock in body.stocks}) != len(body.stocks):
                raise ProjectError(422, "validation_error", "Duplicate stock IDs")
            for stock in body.stocks:
                measurements = (
                    stock.width_mm,
                    stock.height_mm,
                    stock.thickness_mm,
                    stock.remaining_length_mm,
                )
                if any(m.evidence_ids for m in measurements):
                    raise ProjectError(
                        422, "validation_error", "Unresolved media reference"
                    )
                for image_id in stock.image_ids:
                    if (
                        connection.execute(
                            "SELECT 1 FROM media WHERE id=? AND project_id=?",
                            (image_id, project_id),
                        ).fetchone()
                        is None
                    ):
                        raise ProjectError(
                            422, "validation_error", "Unresolved media reference"
                        )
            updated = Project(
                **{
                    **project.model_dump(),
                    "stocks": body.stocks,
                    "inventory_confirmed": True,
                    "revision_id": "inventory-" + uuid4().hex,
                    "requirements": body.requirements
                    if "requirements" in body.model_fields_set
                    else project.requirements,
                }
            )
            connection.execute(
                "UPDATE projects SET body=? WHERE id=? AND owner=?",
                (updated.model_dump_json(), project_id, owner),
            )
            result = ProjectResult(project=updated).model_dump(mode="json")
            store.remember(
                connection, owner, scope, body.idempotency_key, digest, result
            )
            return result

    @router.delete("/{project_id}", response_model=DeleteResult)
    def delete(project_id: ID, owner: Owner, idempotency_key: Annotated[Key, Header()]):
        with store.transaction() as connection:
            scope = project_id + ":delete"
            digest, replay = store.replay(
                connection, owner, scope, idempotency_key, {"project_id": project_id}
            )
            if replay:
                return replay
            store.read(connection, owner, project_id)
            # Purge saved snapshots as well as the live project row.
            connection.execute(
                "DELETE FROM requests WHERE owner=? AND scope=?",
                (owner, project_id + ":inventory"),
            )
            connection.execute(
                "DELETE FROM requests WHERE owner=? AND scope LIKE ?",
                (owner, project_id + ":media:%"),
            )
            connection.execute(
                "DELETE FROM requests WHERE owner=? AND scope IN (?, ?, ?)",
                (
                    owner,
                    project_id + ":plan-preview",
                    project_id + ":plan-activation",
                    project_id + ":design-generation",
                ),
            )
            connection.execute(
                "UPDATE requests SET response=? WHERE owner=? AND scope='create' "
                "AND json_extract(response, '$.project.id')=?",
                (json.dumps({"deleted_project_id": project_id}), owner, project_id),
            )
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
            result = DeleteResult(project_id=project_id).model_dump(mode="json")
            store.remember(connection, owner, scope, idempotency_key, digest, result)
            return result

    from forma_api.media import media_router
    from forma_api.plans import plan_router
    from forma_api.routes.designs import designs_router
    from forma_api.routes.diagnosis import diagnosis_router
    from forma_api.routes.intake import intake_router

    router.include_router(media_router(store, authenticate))
    router.include_router(intake_router(store, authenticate))
    router.include_router(plan_router(store, authenticate))
    router.include_router(designs_router(store, authenticate))
    router.include_router(diagnosis_router(store, authenticate))
    return router
