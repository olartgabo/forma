"""Schema boundaries for mechanical consumer inputs; no pose inference."""

import pytest
from pydantic import ValidationError

from forma_domain.stability_contracts import (
    BodyMass,
    CenterOfMass,
    MechanicalSnapshot,
    Point3,
    QuantityEstimate,
    SupportContact,
)


def scalar(value, unit):
    return QuantityEstimate(
        kind="scalar", unit=unit, value=value, provenance="specified", confirmed=False
    )


def body(**changes):
    data = dict(
        body_id="body",
        source_part_ids=("part",),
        mass=scalar(1.0, "kg"),
        center_of_mass=CenterOfMass(
            x=scalar(0.0, "m"), y=scalar(0.0, "m"), z=scalar(1.0, "m")
        ),
    )
    return BodyMass(**(data | changes))


def snapshot(bodies, contacts=()):
    return MechanicalSnapshot(
        bodies=bodies,
        contacts=contacts,
        rigid_assembly=True,
        horizontal_support=True,
        gravity_only=True,
        state_basis="nominal",
    )


def test_mass_units_positivity_and_duplicate_sources():
    for changes in (
        dict(mass=scalar(0.0, "kg")),
        dict(mass=scalar(1.0, "m")),
        dict(source_part_ids=("part", "part")),
    ):
        with pytest.raises(ValidationError):
            body(**changes)
    with pytest.raises(ValidationError):
        snapshot((body(), body(body_id="other")))
    with pytest.raises(ValidationError):
        snapshot((body(), body()))


def test_bounded_bodies_and_reference_validation():
    with pytest.raises(ValidationError):
        snapshot(
            tuple(body(body_id=f"b{i}", source_part_ids=(f"p{i}",)) for i in range(65))
        )
    contact = SupportContact(
        contact_id="contact",
        body_id="absent",
        active=True,
        polygon_world=(
            Point3(x=0.0, y=0.0, z=0.0),
            Point3(x=1.0, y=0.0, z=0.0),
            Point3(x=0.0, y=1.0, z=0.0),
        ),
    )
    with pytest.raises(ValidationError):
        snapshot((body(),), (contact,))


def test_unknown_mass_is_preserved_and_snapshot_is_immutable():
    unknown = QuantityEstimate(
        kind="unknown", unit="kg", provenance="unknown", confirmed=False
    )
    record = snapshot((body(mass=unknown),))
    assert record.bodies[0].mass.kind == "unknown"
    with pytest.raises(ValidationError):
        record.state_basis = "observed"
    with pytest.raises(ValidationError):
        CenterOfMass(x=scalar(0.0, "kg"), y=scalar(0.0, "m"), z=scalar(0.0, "m"))
