"""Operator check for a server design-context manifest. Local files only.

The API reports an unusable manifest only as "Configured design context is
invalid." so that HTTP callers never learn paths or contents. This command
gives the operator who owns the file the reason, before restarting the API::

    python -m forma_api.design_context_check template \\
        --project-id project-abc --revision-id revision-abc
    python -m forma_api.design_context_check schema
    python -m forma_api.design_context_check check manifest.json \\
        --project-id project-abc --revision-id revision-abc

``template`` prints an entry scoped to the exact project and inventory
revision with every measured fact left empty; fill it only with measured
values and reviewed profiles. ``check`` uses the server's own resolver, so
its verdict matches what design readiness will report, and lists each
validation failure by field location without echoing values. It exits 0
only when exactly one entry matches and no context fact is missing.

The project's current inventory revision comes from the saved-projects list
or the read-only ``forma_api.demo_smoke --project-id`` report. Any inventory
save creates a new revision, which needs its own entry.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from forma_api.design_context import (
    MAX_CONTEXT_BYTES,
    DesignContext,
    DesignContextManifest,
    FileDesignContextResolver,
)
from forma_api.design_runtime import context_missing_inputs


def template(project_id: str, revision_id: str) -> dict:
    entry = DesignContext(project_id=project_id, inventory_revision_id=revision_id)
    return {"contexts": [entry.model_dump(mode="json")]}


def _entries(data) -> list:
    if isinstance(data, dict) and "contexts" in data:
        return DesignContextManifest.model_validate(data).contexts
    if isinstance(data, list):
        return DesignContextManifest(contexts=tuple(data)).contexts
    if isinstance(data, dict):
        return [DesignContext.model_validate(data)]
    raise ValueError("Manifest must be an object, a list or {'contexts': [...]}.")


def _problems(path: Path, project_id: str, revision_id: str) -> list[str]:
    """Why the resolver would call this manifest invalid, without values."""

    if not path.is_file():
        return ["Manifest file does not exist or is not a file."]
    size = path.stat().st_size
    if size > MAX_CONTEXT_BYTES:
        return [f"Manifest is {size} bytes; the limit is {MAX_CONTEXT_BYTES}."]
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except UnicodeDecodeError:
        return ["Manifest is not UTF-8 text."]
    except json.JSONDecodeError as error:
        return [f"Manifest is not valid JSON (line {error.lineno}): {error.msg}."]
    try:
        entries = _entries(data)
    except ValidationError as error:
        return [
            f"{'.'.join(str(part) for part in item['loc']) or 'manifest'}: "
            f"{item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        ]
    except ValueError as error:
        return [str(error)]
    matches = sum(
        1
        for entry in entries
        if entry.project_id == project_id and entry.inventory_revision_id == revision_id
    )
    if matches > 1:
        return [f"{matches} entries match this project and revision; keep exactly one."]
    return []


def check(path: Path, project_id: str, revision_id: str) -> dict:
    resolved = FileDesignContextResolver(path)(project_id, revision_id)
    blockers = [blocker.message for blocker in resolved.blockers]
    invalid = any(b.code == "invalid_reference" for b in resolved.blockers)
    problems = _problems(path, project_id, revision_id) if invalid else []
    missing = [] if blockers else context_missing_inputs(resolved)
    return {
        "project_id": project_id,
        "inventory_revision_id": revision_id,
        "status": "complete" if not blockers and not missing else "incomplete",
        "blockers": blockers,
        "problems": problems,
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forma_api.design_context_check",
        description="Prepare and check a server design-context manifest.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("template", "check"):
        command = commands.add_parser(name)
        if name == "check":
            command.add_argument("manifest", type=Path)
        command.add_argument("--project-id", required=True)
        command.add_argument("--revision-id", required=True)
    commands.add_parser("schema")
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps(DesignContext.model_json_schema(), indent=2))
        return 0
    if args.command == "template":
        try:
            body = template(args.project_id, args.revision_id)
        except ValidationError:
            print("Project or revision ID is not a valid FORMA ID.", file=sys.stderr)
            return 2
        print(json.dumps(body, indent=2))
        return 0
    report = check(args.manifest, args.project_id, args.revision_id)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
