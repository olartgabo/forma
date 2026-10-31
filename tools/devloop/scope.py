"""Paths the loop may write: the @ResniDev lane only."""

from pathlib import PurePosixPath

LANE = (
    "packages/domain/src/",
    "packages/domain/tests/",
    "packages/compiler/",
    "packages/replanner/",
    "packages/renderer/",
    "apps/api/src/forma_api/model_gateway.py",
    "apps/api/src/forma_api/proposal_service.py",
    "apps/api/src/forma_api/proposal_prompts.py",
    "apps/api/tests/test_model_gateway.py",
    "apps/api/tests/test_proposal_service.py",
    "prompts/",
    "scripts/smoke_meta.py",
    "docs/handoffs/",
)
# Shared contracts: allowed, but force the senior judge and a handoff note.
CONTRACT = ("packages/domain/src/",)
FORBIDDEN_PARTS = ("generated", "__pycache__", ".env", "node_modules")
FORBIDDEN_NAMES = ("uv.lock", "package-lock.json")


class ScopeError(Exception):
    pass


def check_path(path: str) -> str:
    """Return the normalized path or raise ScopeError."""
    p = PurePosixPath(path.replace("\\", "/"))
    norm = str(p)
    if p.is_absolute() or ".." in p.parts or not norm or norm == ".":
        raise ScopeError(f"unsafe path: {path}")
    if p.name in FORBIDDEN_NAMES or any(
        part.startswith(f) for part in p.parts for f in FORBIDDEN_PARTS
    ):
        raise ScopeError(f"generated, lock or secret file: {norm}")
    if not norm.startswith(LANE):
        raise ScopeError(f"outside your lane: {norm}")
    return norm


def touches_contract(paths: list[str]) -> bool:
    return any(p.startswith(CONTRACT) for p in paths)
