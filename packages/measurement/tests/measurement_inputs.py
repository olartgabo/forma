"""SYNTHETIC software fixtures for measurement decisions; nothing measured."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "synthesizer/tests"))

from synthetic_inputs import (  # noqa: E402
    UNKNOWN,
    constraints,
    measured,
    search_input,
    tape,
)

from forma_domain import models as m  # noqa: E402

__all__ = [
    "UNKNOWN",
    "constraints",
    "measured",
    "search_input",
    "sheet",
    "strip",
    "tape",
]


def value(v, confirmed=True):
    if v is None:
        return UNKNOWN
    return m.Measurement(
        value=v,
        unit="mm",
        source="user_ruler" if confirmed else "calculated",
        confirmed=confirmed,
    )


def sheet(stock_id, width=None, height=None, thickness=2, confirmed=True, region=False):
    """An app-like sheet: unmeasured sheets have no usable region recorded."""
    return m.Stock(
        id=stock_id,
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=value(width, confirmed),
        height_mm=value(height, confirmed),
        thickness_mm=value(thickness, confirmed),
        remaining_length_mm=UNKNOWN,
        usable_regions=(
            (
                m.Region(
                    id=stock_id + "-region",
                    geometry=m.Rect(x=0, y=0, width=width, height=height),
                ),
            )
            if region
            else ()
        ),
    )


def strip(stock_id="strip-1"):
    return m.Stock(
        id=stock_id,
        kind="strip",
        material="cardboard",
        condition="usable",
        width_mm=UNKNOWN,
        height_mm=UNKNOWN,
        thickness_mm=UNKNOWN,
        remaining_length_mm=UNKNOWN,
    )
