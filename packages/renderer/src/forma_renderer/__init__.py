"""Offline stand template and deterministic SVG manual. No physical claims."""

from .continuation import stand_continuation_blockers
from .diff import ManualDiff, diff_manuals, previous_panel_indices
from .resources import ConnectorContext
from .svg import BillItem, Manual, Panel, render_manual
from .template import StandParameters, compile_stand

__all__ = [
    "BillItem",
    "ConnectorContext",
    "Manual",
    "ManualDiff",
    "Panel",
    "StandParameters",
    "compile_stand",
    "diff_manuals",
    "previous_panel_indices",
    "render_manual",
    "stand_continuation_blockers",
]
