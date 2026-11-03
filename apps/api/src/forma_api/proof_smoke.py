"""Read-only Proof export acceptance command.

Makes exactly two GET requests: ``/api/health`` (no credential) and the
owner-scoped ``/api/projects/{id}/proof`` snapshot. It never sends a POST,
reads no provider status, makes no provider call and mutates nothing. The
owner credential comes only from ``FORMA_SMOKE_OWNER_TOKEN`` or an optional
``--credential-file`` (the same convention as ``forma_api.demo_smoke``); it is
never a command-line value and is never printed.

The live snapshot is validated against the ``ProofSnapshot`` model and then
checked for internal coherence: project/version scope, unique references,
active/historical/preview ancestry, event/evidence/material/invalidation
references, revision relationships, recomputed progress status, cursor and
expected stock, and photo exclusion everywhere (``image_ids`` empty and
``asset_id`` null at every depth, including nested repair simulation plans).

Downloaded exports are verified only when supplied:

* ``--json-export PATH`` is validated and coherence-checked, then compared
  semantically with the live snapshot, excluding only ``generated_at``.
* ``--text-export PATH`` is compared *structurally* with the live snapshot
  (version headings and states, status, counts, references) following the web
  ``proof-report.ts`` layout. This is not an exact-text or browser acceptance
  check, and free-text content is never compared or reproduced.

If either export no longer matches the live snapshot (for example a physical
report was added afterwards) the run fails as changed; it cannot tell a stale
export from an inconsistent one. Without export arguments the report states
``artifact_verification: not_requested``.

The report is one JSON object of booleans, counts and enums. It contains no
goal, notes, tokens, media IDs, file paths, export content, exception text or
server response bodies. A passing run is software consistency only: it never
claims a physical test pass, a provider result or measured dimensions.
"""

import argparse
import json
import os
import stat
import sys
from typing import TextIO
from urllib.parse import urlsplit

from pydantic import ValidationError

from forma_api import demo_smoke
from forma_api.demo_smoke import (
    CREDENTIAL_ENV_VAR,
    DEFAULT_ORIGIN,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    HttpRequest,
    HttpResponse,
    TransportError,
)
from forma_api.progress import expected_stock
from forma_api.projects import ProjectError
from forma_api.proof import ProofSnapshot
from forma_api.routes.health import HealthResponse

MAX_EXPORT_BYTES = 4_000_000
_REDIRECTS = (301, 302, 303, 307, 308)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_STATUS_TEXT = {
    "not_started": "No physical work reported",
    "building": "Build in progress; user reports recorded",
    "needs_review": "Failed check; diagnosis or revision required",
    "passed": "Defined functional test passed; user reported",
}
_STATE_LABEL = {
    "active": "Active plan",
    "historical": "Historical plan",
    "preview": "Saved preview",
}
# Mirrors evidenceLabel in apps/web/src/lib/proof-report.ts.
_EVIDENCE_LABEL = {
    "measurement": "manually measured",
    "user_report": "user report",
    "photo": "photo",
    "physical_test": "physical test",
    "model_interpretation": "Muse observations and hypotheses (unverified)",
}
COVERAGE_LIMITS = (
    "software_consistency_only_no_physical_verification",
    "no_provider_or_media_bytes_checked",
    "user_authored_text_not_inspected",
    "text_export_structural_only_not_exact_text_or_browser_acceptance",
    "export_verification_limited_to_supplied_files",
)


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D102 - argparse hook; never echo input
        raise _ArgumentError("invalid_arguments")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python -m forma_api.proof_smoke",
        allow_abbrev=False,
        description=(
            "Read-only Proof acceptance: health, then one owner-scoped Proof "
            "snapshot validated for schema and internal coherence. Optional "
            "--json-export (semantic comparison excluding generated_at) and "
            "--text-export (structural comparison only) verify downloaded "
            "files against the live snapshot without printing their content. "
            "The report holds booleans, counts and enums only. A pass is "
            "software consistency, never physical evidence."
        ),
        epilog=(
            f"The owner token is read from {CREDENTIAL_ENV_VAR} or "
            "--credential-file, never a command-line value. Exit 0 verified, "
            "1 verification or transport failure, 2 invalid arguments."
        ),
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--api-origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--credential-file", default=None)
    parser.add_argument("--json-export", default=None)
    parser.add_argument("--text-export", default=None)
    return parser


def _normalize_origin(raw: str) -> str | None:
    origin = demo_smoke._normalize_origin(raw)
    if origin is None:
        return None
    parts = urlsplit(origin)
    # The bearer token must not travel in cleartext beyond loopback.
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK_HOSTS:
        return None
    return origin


def _initial_report(origin: str | None) -> dict:
    return {
        "status": "failed",
        "api_origin": origin,
        "health": {"status": "not_checked"},
        "snapshot": {"status": "not_checked"},
        "json_export": {"status": "not_requested"},
        "text_export": {"status": "not_requested"},
        "artifact_verification": "not_requested",
        "coverage_limits": list(COVERAGE_LIMITS),
        "physical_verification": "not_checked",
        "measurements": "unknown",
        "errors": [],
    }


def _fail(report: dict, check: str, code: str, http_status: int | None = None) -> None:
    error: dict = {"check": check, "code": code}
    if http_status is not None:
        error["http_status"] = http_status
    report["errors"].append(error)


# --- Local export files ------------------------------------------------------


def _read_export(path_text: str) -> tuple[str | None, str | None]:
    """Bounded read of one regular UTF-8 file; returns (text, error_code)."""

    try:
        descriptor = os.open(
            path_text,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except (OSError, ValueError):
        return None, "export_unreadable"
    try:
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None, "export_not_regular_file"
            raw = handle.read(MAX_EXPORT_BYTES + 1)
    except OSError:
        return None, "export_unreadable"
    if len(raw) > MAX_EXPORT_BYTES:
        return None, "export_too_large"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "invalid_encoding"


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _reject_constant(_name):
    raise ValueError("non-finite number")


def _parse_snapshot(
    raw: str | bytes,
) -> tuple[tuple[ProofSnapshot, object] | None, str | None]:
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        return None, "invalid_json"
    try:
        return (ProofSnapshot.model_validate(document), document), None
    except ValidationError:
        return None, "invalid_schema"


# --- Snapshot coherence ------------------------------------------------------


def _photo_fields_clear(node) -> bool:
    """No ``image_ids`` or ``asset_id`` survives at any depth."""

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "image_ids" and value != []:
                return False
            if key == "asset_id" and value is not None:
                return False
            if not _photo_fields_clear(value):
                return False
    elif isinstance(node, list):
        return all(_photo_fields_clear(item) for item in node)
    return True


def _expected_states(snapshot: ProofSnapshot) -> dict[str, str]:
    by_id = {item.plan.version_id: item for item in snapshot.versions}
    active_id = snapshot.project.active_version_id
    historical: set[str] = set()
    active = by_id.get(active_id)
    parent = active.plan.parent_version_id if active else None
    while parent in by_id and parent not in historical:
        historical.add(parent)
        parent = by_id[parent].plan.parent_version_id
    return {
        version_id: "active"
        if version_id == active_id
        else "historical"
        if version_id in historical
        else "preview"
        for version_id in by_id
    }


def coherence_checks(snapshot: ProofSnapshot, document) -> dict[str, bool]:
    """Named booleans; every one must hold for a coherent snapshot."""

    project = snapshot.project
    versions = snapshot.versions
    ids = [item.plan.version_id for item in versions]
    by_id = {item.plan.version_id: item for item in versions}
    checks: dict[str, bool] = {}

    checks["photos_excluded"] = _photo_fields_clear(document) and all(
        not stock.image_ids for stock in project.stocks
    )
    checks["version_ids_unique"] = len(ids) == len(set(ids))
    checks["scope_consistent"] = all(
        item.plan.project_id == project.id
        and item.progress.project_id == project.id
        and item.progress.version_id == item.plan.version_id
        and all(
            record.project_id == project.id
            and record.version_id == item.plan.version_id
            for record in (
                *item.progress.events,
                *item.progress.evidence,
                *item.progress.material_transactions,
            )
        )
        for item in versions
    )
    states = _expected_states(snapshot)
    checks["states_match_ancestry"] = all(
        item.state == states[item.plan.version_id] for item in versions
    )
    active_count = sum(item.state == "active" for item in versions)
    checks["active_pointer_consistent"] = (
        active_count == 0
        if project.active_version_id is None
        else active_count == 1 and project.active_version_id in by_id
    )
    chain_complete = True
    for item in versions:
        if item.state in ("active", "historical"):
            parent = item.plan.parent_version_id
            if parent is not None and parent not in by_id:
                chain_complete = False
    checks["ancestry_complete"] = chain_complete

    all_events: list[str] = []
    all_evidence: list[str] = []
    all_material: list[str] = []
    progress_ok = True
    references_ok = True
    stock_ok = True
    for item in versions:
        plan, progress = item.plan, item.progress
        operation_ids = [operation.id for operation in plan.operations]
        operations = set(operation_ids)
        parts = {part.id for part in plan.parts}
        stocks = {stock.id for stock in plan.stocks}
        checkpoints = {checkpoint.id for checkpoint in plan.checkpoints}
        event_ids = [event.id for event in progress.events]
        evidence_ids = {evidence.id for evidence in progress.evidence}
        all_events += event_ids
        all_evidence += [evidence.id for evidence in progress.evidence]
        all_material += [entry.id for entry in progress.material_transactions]

        references_ok &= all(
            event.operation_id in operations | {None}
            and set(event.evidence_ids) <= evidence_ids
            for event in progress.events
        )
        references_ok &= all(
            set(evidence.operation_ids) <= operations
            and set(evidence.part_ids) <= parts
            and set(evidence.checkpoint_ids) <= checkpoints
            for evidence in progress.evidence
        )
        references_ok &= all(
            entry.operation_id in operations
            and entry.source_stock_id in stocks
            and entry.physical_event_id in set(event_ids)
            for entry in progress.material_transactions
        )

        carried = set(progress.carried_operation_ids)
        revision = item.revision
        if revision is not None:
            carried_expected = set(revision.carried_completed_operation_ids)
        else:
            carried_expected = set()
        confirmed = {
            event.operation_id
            for event in progress.events
            if event.kind == "operation_confirmed"
        }
        completed = carried_expected | confirmed
        failed = {
            event.operation_id
            for event in progress.events
            if event.verification_state == "failed"
        }
        if failed:
            status = "needs_review"
        elif progress.events or carried_expected:
            status = (
                "passed"
                if (
                    operations <= completed
                    and any(
                        event.kind == "test" and event.test_result == "passed"
                        for event in progress.events
                    )
                )
                else "building"
            )
        else:
            status = "not_started"
        progress_ok &= (
            progress.completed_operation_ids
            == tuple(op for op in operation_ids if op in completed)
            and progress.carried_operation_ids
            == tuple(op for op in operation_ids if op in carried_expected)
            and progress.failed_operation_ids
            == tuple(op for op in operation_ids if op in failed)
            and carried <= set(progress.completed_operation_ids)
            and progress.last_event_id == (event_ids[-1] if event_ids else None)
            and progress.status == status
        )
        try:
            stock_ok &= progress.expected_remaining_stock == expected_stock(
                plan,
                set(progress.completed_operation_ids),
                progress.material_transactions,
            )
        except (ProjectError, KeyError, ArithmeticError):
            stock_ok = False

    checks["event_ids_unique"] = len(all_events) == len(set(all_events))
    checks["evidence_ids_unique"] = len(all_evidence) == len(set(all_evidence))
    checks["material_ids_unique"] = len(all_material) == len(set(all_material))
    checks["references_resolve"] = references_ok
    checks["progress_recomputes"] = progress_ok
    checks["expected_stock_recomputes"] = stock_ok

    revisions_ok = True
    for item in versions:
        plan, revision = item.plan, item.revision
        parent = plan.parent_version_id
        if revision is None:
            revisions_ok &= parent is None
            continue
        simulation = revision.simulation
        revisions_ok &= (
            parent is not None
            and revision.version_id == plan.version_id
            and revision.base_version_id == parent
            and parent in by_id
            and revision.patch.base_version_id == parent
            and simulation.base_version_id == parent
            and simulation.status == "feasible"
            and simulation.plan is not None
            and simulation.plan.project_id == project.id
            and set(revision.carried_completed_operation_ids)
            <= {operation.id for operation in plan.operations}
        )
    checks["revisions_consistent"] = revisions_ok

    invalidation_ids: list[str] = []
    invalidations_ok = True
    for item in versions:
        evidence_ids = {evidence.id for evidence in item.progress.evidence}
        for invalidation in item.invalidations:
            invalidation_ids.append(invalidation.id)
            target = by_id.get(invalidation.invalidated_for_version_id)
            ancestors: set[str] = set()
            visited = {target.plan.version_id} if target is not None else set()
            parent = target.plan.parent_version_id if target is not None else None
            ancestry_valid = target is not None
            while parent is not None:
                if parent in visited or parent not in by_id:
                    ancestry_valid = False
                    break
                visited.add(parent)
                ancestors.add(parent)
                parent = by_id[parent].plan.parent_version_id
            invalidations_ok &= (
                invalidation.evidence_id in evidence_ids
                and target is not None
                and target.plan.version_id != item.plan.version_id
                and target.revision is not None
                and ancestry_valid
                and item.plan.version_id in ancestors
            )
    checks["invalidations_consistent"] = invalidations_ok and len(
        invalidation_ids
    ) == len(set(invalidation_ids))
    return checks


def _snapshot_counts(snapshot: ProofSnapshot) -> dict:
    versions = snapshot.versions
    return {
        "versions": len(versions),
        "state_counts": {
            state: sum(item.state == state for item in versions)
            for state in ("active", "historical", "preview")
        },
        "revision_count": sum(item.revision is not None for item in versions),
        "event_count": sum(len(item.progress.events) for item in versions),
        "evidence_count": sum(len(item.progress.evidence) for item in versions),
        "material_transaction_count": sum(
            len(item.progress.material_transactions) for item in versions
        ),
        "invalidation_count": sum(len(item.invalidations) for item in versions),
        "photos_omitted": snapshot.photos_omitted,
        "photo_policy": snapshot.photo_policy,
        "coverage": snapshot.coverage,
        "active_version_present": snapshot.project.active_version_id is not None,
    }


# --- Export comparison -------------------------------------------------------


def _comparable(snapshot: ProofSnapshot) -> dict:
    return snapshot.model_dump(mode="json", exclude={"generated_at"})


def _multiline_values(snapshot: ProofSnapshot) -> list[str]:
    """User/model free text that could span lines; masked before parsing."""

    values = [snapshot.project.goal]
    for item in snapshot.versions:
        for event in item.progress.events:
            values.append(event.observation)
        for evidence in item.progress.evidence:
            values.append(evidence.description)
        for invalidation in item.invalidations:
            values.append(invalidation.reason)
        if item.revision is not None:
            values.append(item.revision.patch.rationale)
        for operation in item.plan.operations:
            if operation.type == "functional_test":
                args = operation.args
                values += [args.procedure, args.device_label, args.surface]
                values += list(args.pass_criteria)
    return sorted({value for value in values if "\n" in value}, key=len, reverse=True)


def _ids(values) -> str:
    return ", ".join(values) if values else "None"


def text_structure_matches(text: str, snapshot: ProofSnapshot) -> bool:
    """Structural check of a downloaded text export; never exact equality."""

    for value in _multiline_values(snapshot):
        text = text.replace(value, "\x00")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    else:
        return False
    position = 0

    def take(predicate) -> bool:
        nonlocal position
        if position < len(lines) and predicate(lines[position]):
            position += 1
            return True
        return False

    def take_exact(value: str) -> bool:
        return take(lambda line: line == value)

    def take_prefix(prefix: str) -> bool:
        return take(lambda line: line.startswith(prefix))

    project = snapshot.project
    versions = snapshot.versions
    if not (
        take_exact("FORMA Proof")
        and take_exact("")
        and take_prefix("Goal: ")
        and take_prefix("Snapshot generated: ")
        and take_exact(f"Active version: {project.active_version_id or 'None'}")
        and take_prefix("Coverage: ")
        and take_exact(f"Private photos excluded: {snapshot.photos_omitted}.")
        and take_prefix("Historical outcomes ")
        and take_prefix("Expected stock is calculated")
        and take_prefix("Recorded timestamps are ")
    ):
        return False
    if not versions and not (
        take_exact("")
        and take_exact("No compiled plan or physical result is recorded.")
    ):
        return False
    if not take_exact("Unknown or unconfirmed starting inputs:"):
        return False
    while take(lambda line: line.startswith("  ")):
        pass

    for item in versions:
        plan, progress = item.plan, item.progress
        completed = set(progress.completed_operation_ids)
        confirmed_count = sum(
            event.kind == "operation_confirmed" for event in progress.events
        )
        if not (
            take_exact("")
            and take_exact(f"Version: {plan.version_id} ({_STATE_LABEL[item.state]})")
            and take_exact(f"Inventory revision: {item.inventory_revision_id}")
            and take_exact(f"Candidate: {item.candidate_id}")
            and take_prefix("Compiler: ")
            and take_exact(f"Physical outcome: {_STATUS_TEXT[progress.status]}")
            and take_exact(
                f"Completed operations: {len(progress.completed_operation_ids)}"
                f" / {len(plan.operations)}"
            )
            and take_exact(
                f"Carried from earlier reports: {len(progress.carried_operation_ids)}"
            )
            and take_exact(f"New completion reports in this version: {confirmed_count}")
            and (
                take_prefix("Recorded waste: ")
                if any(
                    entry.kind in ("waste", "salvage")
                    for entry in progress.material_transactions
                )
                else take_exact("No discarded or recovered material recorded.")
            )
        ):
            return False
        revision = item.revision
        if revision is not None:
            simulation = revision.simulation
            for label, expected in (
                ("Revised from", revision.base_version_id),
                ("Approved", None),
                ("Reason", None),
                ("Kept work", _ids(simulation.preserved_operation_ids)),
                (
                    "Physical undo required",
                    _ids(simulation.required_undo_operation_ids),
                ),
                ("Redo", _ids(simulation.redo_operation_ids)),
                ("New work", _ids(simulation.newly_required_operation_ids)),
                ("Changed parts", _ids(simulation.changed_part_ids)),
                ("Lost parts", _ids(simulation.lost_part_ids)),
                ("Lost work", _ids(simulation.lost_operation_ids)),
                ("Lost regions", _ids(simulation.lost_region_ids)),
                (
                    "Additional material stock",
                    _ids(simulation.additional_material_stock_ids),
                ),
                ("New stock required", _ids(simulation.required_new_stock_ids)),
                ("Checks to repeat", _ids(simulation.invalidated_checkpoint_ids)),
                (
                    "Unknown physical checks",
                    _ids(simulation.unknown_physical_checks),
                ),
            ):
                if expected is None:
                    ok = take_prefix(f"{label}: ")
                else:
                    ok = take_exact(f"{label}: {expected}")
                if not ok:
                    return False
            if not take_prefix("Planned material changes (not physical receipts): "):
                return False
        if not take_exact("Uncompleted operations:"):
            return False
        unfinished = [
            f"  {operation.id} ({operation.type})"
            for operation in plan.operations
            if operation.id not in completed
        ]
        for line in unfinished or ["  None"]:
            if not take_exact(line):
                return False
        for operation in plan.operations:
            if operation.type != "functional_test":
                continue
            args = operation.args
            if not (
                take_exact("Defined functional test:")
                and take_exact(f"  Operation: {operation.id}")
                and take_prefix("  Procedure: ")
                and take_prefix("  Device: ")
                and take_prefix("  Mass: ")
                and take_prefix("  Duration: ")
                and take_prefix("  Surface: ")
            ):
                return False
            for _ in args.pass_criteria:
                if not take_prefix("  Criterion: "):
                    return False
            tests = [
                event
                for event in progress.events
                if event.operation_id == operation.id and event.kind == "test"
            ]
            if tests:
                for event in tests:
                    if not take_prefix(f"  User-reported result: {event.test_result};"):
                        return False
            elif not take_exact("  Result: not attempted"):
                return False
        if not take_exact("User report timeline:"):
            return False
        if progress.events:
            for event in progress.events:
                outcome = event.test_result or event.verification_state
                suffix = (
                    f" | {event.operation_id or 'Project'} | {event.kind} | {outcome}"
                )
                if not (
                    take(
                        lambda line, s=suffix: (
                            line.startswith("  ") and line.endswith(s)
                        )
                    )
                    and take_prefix("    ")
                ):
                    return False
        elif not take_exact("  No reports"):
            return False
        if not take_exact("Evidence provenance:"):
            return False
        if progress.evidence:
            for evidence in progress.evidence:
                head = (
                    f"  {evidence.id} | {_EVIDENCE_LABEL[evidence.kind]}"
                    f" | {evidence.provenance}"
                    f" | {evidence.verification_state}"
                )
                if evidence.kind == "photo":
                    head += " | image excluded"
                if not (
                    take_exact(head)
                    and take_prefix("    ")
                    and take_exact(
                        f"    Checkpoints: {', '.join(evidence.checkpoint_ids) or 'None'}"
                    )
                ):
                    return False
                for invalidation in item.invalidations:
                    if invalidation.evidence_id != evidence.id:
                        continue
                    if not take_prefix(
                        f"    Invalidated for {invalidation.invalidated_for_version_id} at "
                    ):
                        return False
        elif not take_exact("  No evidence recorded"):
            return False
        if not take_exact(
            "Material receipts from reported operations and material records:"
        ):
            return False
        if progress.material_transactions:
            for entry in progress.material_transactions:
                if not take_prefix(
                    f"  {entry.operation_id} | {entry.kind} | "
                ) or not lines[position - 1].endswith(
                    f" | {entry.source_stock_id}"
                    + (f" / {entry.source_region_id}" if entry.source_region_id else "")
                ):
                    return False
        elif not take_exact("  No material receipts"):
            return False
        if not take_exact("Expected stock (calculated):"):
            return False
        for stock in progress.expected_remaining_stock:
            if not take_prefix(f"  {stock.id}: "):
                return False
    return position == len(lines)


# --- Run ----------------------------------------------------------------------


def _load_json_export(
    path_text: str,
) -> tuple[tuple[ProofSnapshot, object] | None, str | None]:
    text, error = _read_export(path_text)
    if text is None:
        return None, error
    return _parse_snapshot(text)


def run(argv=None, *, env=None, transport=None, out: TextIO | None = None) -> int:
    """Run the read-only acceptance checks and print one redacted JSON report."""

    env = os.environ if env is None else env
    transport = demo_smoke._http_transport if transport is None else transport
    out = sys.stdout if out is None else out

    try:
        args = _build_parser().parse_args(argv)
    except _ArgumentError:
        report = _initial_report(None)
        _fail(report, "arguments", "invalid_arguments")
        print(json.dumps(report, sort_keys=True), file=out)
        return 2
    except SystemExit as exc:  # --help
        return int(exc.code or 0)

    origin = _normalize_origin(args.api_origin)
    report = _initial_report(origin)

    def emit(code: int) -> int:
        report["status"] = "ok" if code == 0 else "failed"
        print(json.dumps(report, sort_keys=True), file=out)
        return code

    if origin is None:
        _fail(report, "arguments", "invalid_origin")
        return emit(2)
    if not (MIN_TIMEOUT_SECONDS <= args.timeout <= MAX_TIMEOUT_SECONDS):
        _fail(report, "arguments", "invalid_timeout")
        return emit(2)
    if not demo_smoke._ID_RE.match(args.project_id):
        _fail(report, "arguments", "invalid_project_id")
        return emit(2)
    token, credential_error = demo_smoke._load_credential(env, args.credential_file)
    if token is None:
        _fail(report, "credential", credential_error or "credential_missing")
        return emit(2)

    # --- Local exports are read and parsed before any request is made. ---
    exported_json: tuple[ProofSnapshot, object] | None = None
    exported_text: str | None = None
    load_failed = False
    if args.json_export is not None:
        exported_json, error = _load_json_export(args.json_export)
        report["json_export"] = {"status": "failed" if error else "loaded"}
        if error:
            _fail(report, "json_export", error)
            load_failed = True
    if args.text_export is not None:
        exported_text, error = _read_export(args.text_export)
        report["text_export"] = {"status": "failed" if error else "loaded"}
        if error:
            _fail(report, "text_export", error)
            load_failed = True
    if load_failed:
        report["artifact_verification"] = "failed"
        return emit(1)

    def get(path: str, *, authorized: bool) -> HttpResponse:
        headers = {"Accept": "application/json"}
        if authorized:
            headers["Authorization"] = f"Bearer {token}"
        return transport(
            HttpRequest(
                method="GET",
                url=origin + path,
                headers=headers,
                body=None,
                timeout=float(args.timeout),
            )
        )

    def checked(check: str, path: str, *, authorized: bool) -> HttpResponse | None:
        try:
            response = get(path, authorized=authorized)
        except TransportError as exc:
            _fail(report, check, exc.code)
            return None
        except Exception:
            _fail(report, check, "network_error")
            return None
        if len(response.body) > MAX_RESPONSE_BYTES:
            _fail(report, check, "response_too_large")
            return None
        if response.status in _REDIRECTS:
            _fail(report, check, "redirect_rejected", response.status)
            return None
        if not 200 <= response.status < 300:
            _fail(
                report,
                check,
                demo_smoke._safe_http_error_code(response),
                response.status,
            )
            return None
        return response

    # --- Health (public GET, no credential sent). ---
    response = checked("health", "/api/health", authorized=False)
    if response is None:
        report["health"] = {"status": "failed"}
        return emit(1)
    try:
        health = HealthResponse.model_validate_json(response.body)
    except ValidationError:
        report["health"] = {"status": "failed"}
        _fail(report, "health", "invalid_response")
        return emit(1)
    report["health"] = {"status": health.status}

    # --- Owner-scoped Proof snapshot (single GET). ---
    response = checked(
        "snapshot", f"/api/projects/{args.project_id}/proof", authorized=True
    )
    if response is None:
        report["snapshot"] = {"status": "failed"}
        return emit(1)
    parsed, error = _parse_snapshot(response.body)
    if parsed is None:
        report["snapshot"] = {"status": "failed"}
        _fail(report, "snapshot", "invalid_response")
        return emit(1)
    live, live_document = parsed
    checks = coherence_checks(live, live_document)
    checks["project_matches_request"] = live.project.id == args.project_id
    checks["cache_prevented"] = (
        "no-store" in response.headers.get("cache-control", "").lower()
    )
    failed = sorted(name for name, ok in checks.items() if not ok)
    report["snapshot"] = {
        "status": "ok" if not failed else "failed",
        **_snapshot_counts(live),
        "checks": dict(sorted(checks.items())),
        "failed_checks": failed,
    }
    if failed:
        _fail(report, "snapshot", "snapshot_incoherent")
        report["artifact_verification"] = (
            "failed"
            if (exported_json or exported_text is not None)
            else "not_requested"
        )
        return emit(1)

    # --- Exports against the live snapshot. ---
    verified: list[str] = []
    export_failed = False
    if exported_json is not None:
        export, export_document = exported_json
        export_checks = coherence_checks(export, export_document)
        export_checks["same_project"] = export.project.id == live.project.id
        export_checks["generated_not_after_current"] = (
            export.generated_at <= live.generated_at
        )
        export_failed_checks = sorted(n for n, ok in export_checks.items() if not ok)
        matches = _comparable(export) == _comparable(live)
        result = {
            "status": "verified" if matches and not export_failed_checks else "failed",
            "semantic_match_excluding_generated_at": matches,
            "failed_checks": export_failed_checks,
            "comparison": "semantic_json_excluding_generated_at",
        }
        report["json_export"] = result
        if result["status"] != "verified":
            export_failed = True
            _fail(
                report,
                "json_export",
                "snapshot_changed" if not matches else "snapshot_incoherent",
            )
        else:
            verified.append("json_semantic")
    if exported_text is not None:
        matches = text_structure_matches(exported_text, live)
        report["text_export"] = {
            "status": "verified" if matches else "failed",
            "structural_match": matches,
            "comparison": "structural_only",
        }
        if matches:
            verified.append("text_structural")
        else:
            export_failed = True
            _fail(report, "text_export", "text_structure_mismatch")
    if export_failed:
        report["artifact_verification"] = "failed"
        return emit(1)
    report["artifact_verification"] = (
        "+".join(verified) if verified else "not_requested"
    )
    return emit(0)


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
