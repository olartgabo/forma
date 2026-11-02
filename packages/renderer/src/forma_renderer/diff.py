"""Offline diff of rendered manuals. No physical claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .svg import Manual


@dataclass(frozen=True)
class ManualDiff:
    """Panel indices in ascending order.

    In positional (legacy) mode every index is a 0-based panel position in
    the corresponding manual. In keyed mode ``unchanged``, ``changed`` and
    ``added`` are 0-based indices into the new manual, while ``removed``
    holds 0-based indices into the old manual.
    """

    unchanged: tuple[int, ...]
    changed: tuple[int, ...]
    added: tuple[int, ...]
    removed: tuple[int, ...]


def diff_manuals(old: Manual, new: Manual) -> ManualDiff:
    """Compare manuals using ``dependency_hash``, aligning by ``step_key`` when keyed.

    Key fallback rules: if every panel in both manuals has
    ``step_key is None``, panels are compared by position exactly as legacy
    manuals always were. If any panel has a non-``None`` ``step_key``, keyed
    comparison is required: every panel of each non-empty manual must then
    have a non-empty ``str`` ``step_key`` that is unique within that manual,
    otherwise ``ValueError`` is raised and there is no silent fallback to
    positional comparison. An empty manual is neutral in keyed mode (all of
    the other manual's panels are ``added``, or all ``removed``).

    In keyed mode panels are aligned by ``step_key`` alone and compared only
    by their existing ``dependency_hash``; SVG text is never parsed and
    operation IDs are not compared. ``unchanged``/``changed``/``added`` are
    indices into ``new`` and ``removed`` indices into ``old``, each in
    ascending enumeration order.

    A matching hash only means the visible panel is identical. It says
    nothing about checkpoint freshness, evidence validity or physical state.

    Pure and offline: performs no I/O and mutates neither manual.
    """
    if all(panel.step_key is None for manual in (old, new) for panel in manual.panels):
        old_hashes = tuple(panel.dependency_hash for panel in old.panels)
        new_hashes = tuple(panel.dependency_hash for panel in new.panels)
        shared = min(len(old_hashes), len(new_hashes))
        unchanged = tuple(i for i in range(shared) if old_hashes[i] == new_hashes[i])
        changed = tuple(i for i in range(shared) if old_hashes[i] != new_hashes[i])
        added = tuple(range(shared, len(new_hashes)))
        removed = tuple(range(shared, len(old_hashes)))
        return ManualDiff(
            unchanged=unchanged,
            changed=changed,
            added=added,
            removed=removed,
        )

    def keyed(manual: Manual) -> dict[str, tuple[int, str]]:
        by_key: dict[str, tuple[int, str]] = {}
        for index, panel in enumerate(manual.panels):
            key = panel.step_key
            if not isinstance(key, str) or not key:
                raise ValueError(
                    "Keyed manual diff requires every panel of a non-empty "
                    "manual to have a non-empty step_key."
                )
            if key in by_key:
                raise ValueError(f"Duplicate step_key {key!r} within a single manual.")
            by_key[key] = (index, panel.dependency_hash)
        return by_key

    old_by_key = keyed(old)
    new_by_key = keyed(new)
    unchanged: list[int] = []
    changed: list[int] = []
    added: list[int] = []
    for new_index, panel in enumerate(new.panels):
        match = old_by_key.get(panel.step_key)  # type: ignore[arg-type]
        if match is None:
            added.append(new_index)
        elif match[1] == panel.dependency_hash:
            unchanged.append(new_index)
        else:
            changed.append(new_index)
    removed = tuple(
        old_index
        for key, (old_index, _hash) in old_by_key.items()
        if key not in new_by_key
    )
    return ManualDiff(
        unchanged=tuple(unchanged),
        changed=tuple(changed),
        added=tuple(added),
        removed=removed,
    )
