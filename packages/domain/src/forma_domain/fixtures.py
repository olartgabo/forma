"""Synthetic software fixture; never a measured inventory or physical pass."""

from .models import Measurement, Rect, Region, Stock


def synthetic_inventory_a() -> tuple[Stock, ...]:
    def dimension(value):
        return Measurement(value=value, unit="mm", source="calculated", confirmed=False)

    unknown = Measurement(value=None, unit="mm", source="unknown", confirmed=False)
    return (
        Stock(
            id="synthetic-stock-a",
            kind="sheet",
            material="cardboard",
            width_mm=dimension(300),
            height_mm=dimension(200),
            thickness_mm=unknown,
            remaining_length_mm=unknown,
            condition="uncertain",
            usable_regions=(
                Region(
                    id="synthetic-region-a",
                    geometry=Rect(x=0, y=0, width=300, height=200),
                ),
            ),
        ),
    )
