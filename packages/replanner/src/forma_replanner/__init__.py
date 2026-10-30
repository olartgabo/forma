"""Offline repair previews; no approval, history writes or physical claims."""

from .simulation import (
    MaterialDelta,
    RepairCost,
    SimulationResult,
    rank_feasible,
    simulate_patch,
)

__all__ = [
    "MaterialDelta",
    "RepairCost",
    "SimulationResult",
    "rank_feasible",
    "simulate_patch",
]
