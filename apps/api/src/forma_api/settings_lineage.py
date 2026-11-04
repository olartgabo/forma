"""Design settings that survive measurement corrections (#149).

Server design settings (cutting process, stand parameters, reviewed profiles,
kerf and margin) are reviewed for one inventory revision. When the current
revision has no settings of its own, the newest earlier revision that has them
is used, but only for stock that is still the same physical item: the same
stable stock ID, kind and material in every revision since. Only measured facts
(dimensions, thickness, remaining length, usable area, condition, photos) may
have changed; the search, the compiler and the fabrication report then recheck
everything against the current values.

Stock added, removed and added again, or changed in kind or material is left
out and named; removed stock is named. A changed tool list drops only the tool
confirmation. Evidence is carried exactly as recorded: nothing is renewed,
confirmed or re-dated, and evidence not in a confirmed state is named.

History comes from the inventory route's own request receipts, which hold the
saved project for each revision. They are only read, never changed. Without a
complete history the settings are not carried and the operator prerequisite
stays.
"""

import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError

from forma_api.design_context import ResolvedDesignContext
from forma_api.projects import Project
from forma_domain.models import Stock

MAX_HISTORY = 64
CONFIRMED_STATES = {"user_confirmed"}


@dataclass(frozen=True)
class Revision:
    revision_id: str
    stocks: tuple[Stock, ...]
    tools: tuple[str, ...] | None


@dataclass(frozen=True)
class Settings:
    """The settings to use for the current revision and what they cover.

    ``covered`` is None when the settings are the revision's own; otherwise it
    names the stock IDs the carried settings apply to.
    """

    resolved: ResolvedDesignContext
    covered: frozenset[str] | None = None
    notes: tuple[str, ...] = ()
    source_revision_id: str | None = None


def history(connection, owner: str, project: Project) -> tuple[Revision, ...]:
    """Saved inventory revisions, newest first, from the inventory receipts."""
    rows = connection.execute(
        "SELECT response FROM requests WHERE owner=? AND scope=? "
        "ORDER BY rowid DESC LIMIT ?",
        (owner, project.id + ":inventory", MAX_HISTORY),
    ).fetchall()
    seen, revisions = set(), []
    for (raw,) in rows:
        try:
            saved = Project.model_validate(json.loads(raw)["project"])
        except (ValueError, KeyError, TypeError, ValidationError):
            # An unreadable receipt breaks the chain: carry nothing past it.
            break
        if saved.id != project.id or saved.revision_id in seen:
            continue
        seen.add(saved.revision_id)
        revisions.append(
            Revision(
                revision_id=saved.revision_id,
                stocks=saved.stocks,
                tools=tuple(saved.requirements.tools) if saved.requirements else None,
            )
        )
    return tuple(revisions)


def unconfigured(resolved: ResolvedDesignContext) -> bool:
    """The resolver has no entry for the revision (not an invalid manifest)."""
    return (
        resolved.process is None
        and resolved.parameters is None
        and not resolved.joint_profiles
        and len(resolved.blockers) == 1
        and resolved.blockers[0].code == "missing_measurement"
    )


def _describe(stock: Stock) -> str:
    return f"{stock.material} {stock.kind}"


def _evidence_notes(resolved: ResolvedDesignContext) -> list[str]:
    evidence = list(resolved.process.evidence if resolved.process else ())
    if resolved.parameters is not None:
        evidence += list(resolved.parameters.profile_evidence)
    return [
        f"Evidence {e.id} is recorded as {e.verification_state}. A measurement "
        "does not renew it; it needs the operator's review."
        for e in sorted(evidence, key=lambda e: e.id)
        if e.verification_state not in CONFIRMED_STATES
        and not (
            e.provenance == "synthetic_fixture" and e.verification_state == "unknown"
        )
    ]


def settings_for(
    project: Project,
    revisions: tuple[Revision, ...],
    resolver,
    exact: ResolvedDesignContext,
) -> Settings:
    """The revision's own settings, or settings carried from an earlier one."""
    if not unconfigured(exact):
        return Settings(resolved=exact)
    current = {s.id: s for s in project.stocks}
    # The chain must start at the current revision and be unbroken.
    if not revisions or revisions[0].revision_id != project.revision_id:
        return Settings(resolved=exact)
    for index, source in enumerate(revisions[1:], start=1):
        resolved = resolver(project.id, source.revision_id)
        if unconfigured(resolved):
            continue
        if resolved.blockers:
            # The earlier entry is invalid; never carry from it.
            return Settings(resolved=exact)
        return _carry(project, current, revisions[: index + 1], source, resolved)
    return Settings(resolved=exact)


def _carry(project, current, chain, source, resolved) -> Settings:
    since = source.revision_id
    notes = [
        f"Design settings reviewed for inventory revision {since} are used: since "
        "then only measured values of the same stock items changed. They are "
        "rechecked against the current measurements; no evidence is renewed or "
        "confirmed."
    ]
    covered = set()
    for stock_id in sorted(current):
        stock = current[stock_id]
        versions = [
            next((s for s in revision.stocks if s.id == stock_id), None)
            for revision in chain
        ]
        if versions[-1] is None:
            notes.append(
                f"Stock {stock_id} was added after the settings were reviewed; it "
                "stays out of the search until settings that include it are configured."
            )
        elif any(v is None for v in versions):
            notes.append(
                f"Stock {stock_id} was removed and added again since the settings "
                "were reviewed; it is treated as a different item and stays out of "
                "the search."
            )
        elif any(
            (v.kind, v.material) != (stock.kind, stock.material) for v in versions
        ):
            notes.append(
                f"Stock {stock_id} changed from {_describe(versions[-1])} to "
                f"{_describe(stock)} since the settings were reviewed; the reviewed "
                "process and profiles do not cover it, so it stays out of the search."
            )
        else:
            covered.add(stock_id)
    for removed in sorted({s.id for s in source.stocks} - set(current)):
        notes.append(
            f"Stock {removed} was removed since the settings were reviewed; the "
            "settings still apply to the remaining stock."
        )
    parameters = resolved.parameters
    tools = tuple(project.requirements.tools) if project.requirements else None
    if parameters is not None and tools != source.tools and parameters.tools_confirmed:
        parameters = parameters.model_copy(update={"tools_confirmed": False})
        notes.append(
            "The declared tools changed since the settings were reviewed; the tool "
            "confirmation is not carried and must be reviewed again."
        )
    notes += _evidence_notes(resolved)
    payload = {
        "carried_from": since,
        "source_fingerprint": resolved.fingerprint,
        "revision": project.revision_id,
        "covered": sorted(covered),
        "notes": notes,
        "parameters": parameters.model_dump(mode="json") if parameters else None,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Settings(
        resolved=ResolvedDesignContext(
            process=resolved.process,
            parameters=parameters,
            joint_profiles=resolved.joint_profiles,
            kerf_mm=resolved.kerf_mm,
            edge_margin_mm=resolved.edge_margin_mm,
            blockers=(),
            fingerprint=fingerprint,
        ),
        covered=frozenset(covered),
        notes=tuple(notes),
        source_revision_id=since,
    )
