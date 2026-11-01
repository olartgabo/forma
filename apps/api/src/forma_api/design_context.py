"""Server-owned design context resolution. Never supplied by HTTP callers."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from forma_compiler import CutProcess
from forma_renderer import StandParameters
from pydantic import Field, ValidationError

from forma_domain.models import ID, Blocker, JointProfile, Nonnegative, Record

MAX_CONTEXT_BYTES = 262_144
ENV_VAR = "FORMA_DESIGN_CONTEXT_PATH"


class DesignContext(Record):
    """One manifest entry scoped to an exact project and inventory revision."""

    project_id: ID
    inventory_revision_id: ID
    process: CutProcess | None = None
    parameters: StandParameters | None = None
    joint_profiles: tuple[JointProfile, ...] = Field(default=(), max_length=32)
    kerf_mm: Nonnegative | None = None
    edge_margin_mm: Nonnegative | None = None


class DesignContextManifest(Record):
    contexts: tuple[DesignContext, ...] = Field(max_length=64)


@dataclass(frozen=True)
class ResolvedDesignContext:
    process: CutProcess | None = None
    parameters: StandParameters | None = None
    joint_profiles: tuple[JointProfile, ...] = ()
    kerf_mm: float | None = None
    edge_margin_mm: float | None = None
    blockers: tuple[Blocker, ...] = ()
    fingerprint: str = ""

    @classmethod
    def from_context(cls, context: DesignContext, blockers=()):
        payload = context.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "context": payload,
                    "blockers": [b.model_dump(mode="json") for b in blockers],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return cls(
            process=context.process,
            parameters=context.parameters,
            joint_profiles=context.joint_profiles,
            kerf_mm=context.kerf_mm,
            edge_margin_mm=context.edge_margin_mm,
            blockers=tuple(blockers),
            fingerprint=digest,
        )

    @classmethod
    def missing(cls, message: str, code: str = "missing_measurement"):
        blocker = Blocker(code=code, message=message)
        digest = hashlib.sha256(
            json.dumps(
                {"blocker": blocker.model_dump(mode="json")}, sort_keys=True
            ).encode()
        ).hexdigest()
        return cls(blockers=(blocker,), fingerprint=digest)


def _invalid():
    return ResolvedDesignContext.missing(
        "Configured design context is invalid.", code="invalid_reference"
    )


class FileDesignContextResolver:
    """Bounded manifest reader; exact scope only, no fallback, no path leakage."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def __call__(
        self, project_id: str, inventory_revision_id: str
    ) -> ResolvedDesignContext:
        try:
            if not self._path.is_file():
                return _invalid()
            if self._path.stat().st_size > MAX_CONTEXT_BYTES:
                return _invalid()
            raw = self._path.read_bytes()
            if len(raw) > MAX_CONTEXT_BYTES:
                return _invalid()
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return _invalid()
        try:
            if isinstance(data, dict) and "contexts" in data:
                entries = DesignContextManifest.model_validate(data).contexts
            elif isinstance(data, list):
                entries = DesignContextManifest(contexts=tuple(data)).contexts
            elif isinstance(data, dict):
                entries = (DesignContext.model_validate(data),)
            else:
                return _invalid()
        except (ValidationError, ValueError):
            return _invalid()
        matches = [
            entry
            for entry in entries
            if entry.project_id == project_id
            and entry.inventory_revision_id == inventory_revision_id
        ]
        if len(matches) > 1:
            return _invalid()
        if not matches:
            return ResolvedDesignContext.missing(
                "No server-configured design context for this project and inventory revision."
            )
        return ResolvedDesignContext.from_context(matches[0])


class MissingDesignContextResolver:
    def __call__(
        self, project_id: str, inventory_revision_id: str
    ) -> ResolvedDesignContext:
        return ResolvedDesignContext.missing(
            "No server-configured design context for this project and inventory revision."
        )


class StaticDesignContextResolver:
    """Injectable resolver for tests and explicit server wiring."""

    def __init__(self, context: DesignContext | ResolvedDesignContext | None):
        self._context = context

    def __call__(
        self, project_id: str, inventory_revision_id: str
    ) -> ResolvedDesignContext:
        if self._context is None:
            return MissingDesignContextResolver()(project_id, inventory_revision_id)
        if isinstance(self._context, ResolvedDesignContext):
            return self._context
        if (
            self._context.project_id != project_id
            or self._context.inventory_revision_id != inventory_revision_id
        ):
            return ResolvedDesignContext.missing(
                "No server-configured design context for this project and inventory revision."
            )
        return ResolvedDesignContext.from_context(self._context)


def default_context_resolver():
    """Configured only by FORMA_DESIGN_CONTEXT_PATH; never at import time."""

    path = os.environ.get(ENV_VAR, "").strip()
    if not path:
        return MissingDesignContextResolver()
    return FileDesignContextResolver(path)
