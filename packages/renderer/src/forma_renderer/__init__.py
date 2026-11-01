"""Offline stand template and deterministic SVG manual. No physical claims."""

from .continuation import stand_continuation_blockers
from .svg import BillItem, Manual, Panel, render_manual
from .template import StandParameters, compile_stand

__all__ = [
    "BillItem",
    "Manual",
    "Panel",
    "StandParameters",
    "compile_stand",
    "render_manual",
    "stand_continuation_blockers",
]
