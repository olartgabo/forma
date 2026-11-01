"""Paths the loop may write: the @ResniDev lane only."""

from pathlib import Path, PurePosixPath, PureWindowsPath

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
FORBIDDEN_PARTS = (
    "generated",
    "__pycache__",
    ".env",
    "node_modules",
    ".git",
    ".ssh",
    ".aws",
    ".meta-budget",
    ".devloop",
)
FORBIDDEN_NAMES = ("uv.lock", "package-lock.json")
SECRET_NAMES = {"credential", "credentials", "secret", "secrets", "token", "tokens"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".dpapi"}


class ScopeError(Exception):
    pass


def check_path(path: str) -> str:
    """Return the normalized path or raise ScopeError."""
    if not isinstance(path, str) or "\x00" in path:
        raise ScopeError("invalid path")
    windows = PureWindowsPath(path)
    p = PurePosixPath(path.replace("\\", "/"))
    norm = str(p)
    if (
        windows.drive
        or windows.root
        or p.is_absolute()
        or ".." in p.parts
        or not norm
        or norm == "."
        or any(
            ":" in part
            or part.endswith((" ", "."))
            or PureWindowsPath(part).is_reserved()
            for part in p.parts
        )
    ):
        raise ScopeError(f"unsafe path: {path}")
    if (
        p.name.lower() in FORBIDDEN_NAMES
        or p.suffix.lower() in SECRET_SUFFIXES
        or any(
            part.lower().lstrip(".").split(".")[0] in SECRET_NAMES for part in p.parts
        )
        or any(part.lower().startswith(f) for part in p.parts for f in FORBIDDEN_PARTS)
    ):
        raise ScopeError(f"generated, lock or secret file: {norm}")
    if not any(
        norm.startswith(entry) if entry.endswith("/") else norm == entry
        for entry in LANE
    ):
        raise ScopeError(f"outside your lane: {norm}")
    return norm


def resolve_path(root: Path, path: str) -> Path:
    """Validate both the requested path and its actual filesystem destination."""
    norm = check_path(path)
    try:
        base = root.resolve(strict=True)
        target = (base / norm).resolve()
        relative = target.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ScopeError(f"path escapes or cannot resolve in worktree: {norm}") from exc
    check_path(relative.as_posix())
    # Reject aliases even within the lane: a listed write must not change a
    # different file, and a permitted read must not disguise its actual source.
    if target != base / norm:
        raise ScopeError(f"linked path is not allowed: {norm}")
    return target


def touches_contract(paths: list[str]) -> bool:
    return any(p.startswith(CONTRACT) for p in paths)
