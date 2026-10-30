"""Pure deterministic validation; accepted means machine checks, never physical proof."""

from .process import CutProcess
from .validation import validate_plan

__all__ = ["CutProcess", "validate_plan"]
