"""Mechanical recording does not erase units, unknowns or required cases."""

import copy

import pytest
from pydantic import ValidationError

from forma_domain.stability_measurements import StabilityMeasurements


def sample():
    body = dict(
        mass_kg=0.2,
        center_of_mass_m=dict(x=0.0, y=0.05, z=0.1),
        mass_resolution_kg=0.001,
        position_resolution_m=0.001,
        method="Software fixture only",
    )
    return dict(
        stand=body,
        cases=[
            dict(
                orientation=o,
                device=copy.deepcopy(body),
                pose_description="Software fixture pose",
            )
            for o in ("portrait", "landscape")
        ],
        support=dict(
            x_min_m=-0.04,
            x_max_m=0.04,
            y_min_m=0.0,
            y_max_m=0.1,
            resolution_m=0.001,
            method="Software contact fixture",
        ),
        required_margin_m=0.001,
        stand_includes_all_parts_and_connectors=True,
        actual_contacts_confirmed=True,
        rigid_assembly_assumed=True,
        horizontal_surface_confirmed=True,
        stationary_device_assumed=True,
        gravity_only_assumed=True,
    )


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), -1.0, 0.0, True, "0.2"]
)
def test_mass_requires_actual_finite_positive_number(value):
    data = sample()
    data["stand"]["mass_kg"] = value
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "stand_includes_all_parts_and_connectors",
        "actual_contacts_confirmed",
        "rigid_assembly_assumed",
        "horizontal_surface_confirmed",
        "stationary_device_assumed",
        "gravity_only_assumed",
    ],
)
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_each_observation_or_assumption_requires_explicit_boolean(field, value):
    data = sample()
    data[field] = value
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)


def test_units_and_resolution_cannot_be_silently_replaced():
    data = sample()
    data["stand"]["mass_kg"] = None
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)
    data = sample()
    data["stand"]["unit"] = "g"
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)
    data = sample()
    data["stand"]["mass_resolution_kg"] = 0.2
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)
    data = sample()
    data["support"]["x_min_m"] = data["support"]["x_max_m"]
    with pytest.raises(ValidationError):
        StabilityMeasurements.model_validate(data)
    assert len(StabilityMeasurements.model_validate(sample()).cases) == 2
