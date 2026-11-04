"""Deterministic measurement decisions (#149). Offline; never confirms a value."""

from .decide import (
    SELECTION_RULE,
    ActiveFacts,
    CaseMargin,
    Thresholds,
    active_decision,
    compare,
    design_decision,
    thresholds,
)

__all__ = [
    "SELECTION_RULE",
    "ActiveFacts",
    "CaseMargin",
    "Thresholds",
    "active_decision",
    "compare",
    "design_decision",
    "thresholds",
]
