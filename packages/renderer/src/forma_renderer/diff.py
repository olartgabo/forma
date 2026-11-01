"""Offline position-based diff of rendered manuals. No physical claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .svg import Manual


@dataclass(frozen=True)
class ManualDiff:
    """0-based panel positions in ascending order."""

    unchanged: tuple[int, ...]
    changed: tuple[int, ...]
    added: tuple[int, ...]
    removed: tuple[int, ...]


def diff_manuals(old: Manual, new: Manual) -> ManualDiff:
    """Compare manuals by operation position using ``dependency_hash``.

    A position present in both manuals with equal ``dependency_hash`` is
    unchanged; with different hashes it is changed. Positions only in ``new``
    are added and positions only in ``old`` are removed.

    A matching hash only means the visible panel is identical. It says nothing
    about checkpoint freshness, evidence validity or physical state.

    Pure and offline: compares only panel count and ``dependency_hash`` without
    reading ``Panel.svg`` text, performing I/O, or mutating either manual.
    """
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
