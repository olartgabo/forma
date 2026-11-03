"""User-reported SI mechanical measurements; independent from physical test success."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .models import ID, Record, Text
from .stability_contracts import Point3

Positive = Annotated[float, Field(gt=0, strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, strict=True, allow_inf_nan=False)]


class MeasuredBody(Record):
    mass_kg: Positive
    center_of_mass_m: Point3
    mass_resolution_kg: Positive
    position_resolution_m: Positive
    method: Text

    @model_validator(mode="after")
    def plausible_resolution(self):
        if self.mass_resolution_kg >= self.mass_kg:
            raise ValueError("Mass resolution must be smaller than measured mass")
        if self.center_of_mass_m.z < 0:
            raise ValueError("World center of mass must be above the support plane")
        return self


class MeasuredDeviceCase(Record):
    orientation: Literal["portrait", "landscape"]
    device: MeasuredBody
    pose_description: Text


class MeasuredSupportRectangle(Record):
    x_min_m: float = Field(strict=True, allow_inf_nan=False)
    x_max_m: float = Field(strict=True, allow_inf_nan=False)
    y_min_m: float = Field(strict=True, allow_inf_nan=False)
    y_max_m: float = Field(strict=True, allow_inf_nan=False)
    resolution_m: Positive
    method: Text

    @model_validator(mode="after")
    def nondegenerate(self):
        if self.x_min_m >= self.x_max_m or self.y_min_m >= self.y_max_m:
            raise ValueError("Supporting rectangle requires positive spans")
        if self.resolution_m >= min(
            self.x_max_m - self.x_min_m, self.y_max_m - self.y_min_m
        ):
            raise ValueError("Contact resolution must be smaller than its spans")
        return self


class StabilityMeasurements(Record):
    stand: MeasuredBody
    cases: tuple[MeasuredDeviceCase, ...] = Field(min_length=2, max_length=2)
    support: MeasuredSupportRectangle
    required_margin_m: Nonnegative
    stand_includes_all_parts_and_connectors: Literal[True]
    actual_contacts_confirmed: Literal[True]
    rigid_assembly_assumed: Literal[True]
    horizontal_surface_confirmed: Literal[True]
    stationary_device_assumed: Literal[True]
    gravity_only_assumed: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit_checks(cls, value):
        if isinstance(value, dict):
            fields = (
                "stand_includes_all_parts_and_connectors",
                "actual_contacts_confirmed",
                "rigid_assembly_assumed",
                "horizontal_surface_confirmed",
                "stationary_device_assumed",
                "gravity_only_assumed",
            )
            if any(value.get(name) is not True for name in fields):
                raise ValueError(
                    "Every physical observation and applicability assumption requires explicit confirmation"
                )
        return value

    @model_validator(mode="after")
    def required_cases(self):
        if {case.orientation for case in self.cases} != {"portrait", "landscape"}:
            raise ValueError(
                "Supply exactly one portrait and one landscape device case"
            )
        return self


class StabilityMeasurementRecord(Record):
    id: ID
    project_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    based_on_last_event_id: ID | None
    event_id: ID
    evidence_id: ID
    geometry_basis_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    recorded_at: AwareDatetime
    source_part_ids: tuple[ID, ...] = Field(min_length=1, max_length=16)
    measurements: StabilityMeasurements
