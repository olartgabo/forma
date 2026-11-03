"""Immutable user measurements and the bounded measured-to-mechanics adapter."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import model_validator

from forma_api.projects import Key, ProjectError
from forma_domain.models import ID, Evidence, PhysicalEvent, Record
from forma_domain.stability_contracts import AnalysisPolicy, StabilityInput
from forma_domain.stability_measurements import (
    StabilityMeasurementRecord,
    StabilityMeasurements,
)


class StabilityMeasurementRequest(Record):
    plan_version_id: ID
    expected_inventory_revision_id: ID
    expected_last_event_id: ID | None
    idempotency_key: Key
    user_confirmed: Literal[True]
    measurements: StabilityMeasurements

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict) and value.get("user_confirmed") is not True:
            raise ValueError("Measurement capture requires explicit user confirmation")
        return value


class StabilityMeasurementResponse(Record):
    project_id: ID
    plan_version_id: ID
    inventory_revision_id: ID
    last_event_id: ID
    measurement_id: ID
    evidence_id: ID
    replayed: bool = False


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def geometry_basis(geometry):
    # Measurement events change the global cursor, not the shape. Bind the
    # physical producer data separately, with the exact history on the record.
    return digest(
        geometry.model_dump(mode="json", exclude={"geometry_hash", "history_cursor"})
    )


def latest_record(connection, project_id, version_id):
    row = connection.execute(
        "SELECT body FROM stability_measurements WHERE project_id=? AND version_id=? ORDER BY rowid DESC LIMIT 1",
        (project_id, version_id),
    ).fetchone()
    return (
        None if row is None else StabilityMeasurementRecord.model_validate_json(row[0])
    )


def typed_evidence_ids(connection, project_id, version_id):
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT json_extract(body, '$.evidence_id') FROM stability_measurements WHERE project_id=? AND version_id=? ORDER BY rowid",
            (project_id, version_id),
        )
    )


def validate_contact(geometry, measurements):
    if geometry.stage != "reported_assembled":
        raise ValueError(
            "Record assembly steps before saving assembled-stand measurements"
        )
    xs = [p.x for p in geometry.ground_polygon]
    ys = [p.y for p in geometry.ground_polygon]
    support = measurements.support
    if not (
        min(xs) <= support.x_min_m < support.x_max_m <= max(xs)
        and min(ys) <= support.y_min_m < support.y_max_m <= max(ys)
    ):
        raise ValueError(
            "Measured support rectangle must lie within the canonical base footprint"
        )


def save_measurements(connection, store, owner, snapshot, body):
    from forma_api.stability_geometry import preview_geometry

    project = snapshot.project
    scope = project.id + ":stability-measurements"
    hashed, replay = store.replay(
        connection, owner, scope, body.idempotency_key, body.model_dump(mode="json")
    )
    if replay is not None:
        return StabilityMeasurementResponse.model_validate(replay)
    if (
        project.active_version_id != body.plan_version_id
        or project.revision_id != body.expected_inventory_revision_id
        or snapshot.last_event_id != body.expected_last_event_id
    ):
        raise ProjectError(
            409,
            "stale_version",
            "Plan, inventory or physical history changed; reload measurements",
        )
    try:
        geometry = preview_geometry(snapshot)
        validate_contact(geometry, body.measurements)
    except ValueError as error:
        raise ProjectError(422, "validation_error", str(error)) from None
    now = datetime.now(UTC)
    if snapshot.history_events and now <= snapshot.history_events[-1].recorded_at:
        now = snapshot.history_events[-1].recorded_at + timedelta(microseconds=1)
    record_id, event_id, evidence_id = (
        prefix + uuid4().hex for prefix in ("measurement-", "event-", "evidence-")
    )
    record = StabilityMeasurementRecord(
        id=record_id,
        project_id=project.id,
        plan_version_id=body.plan_version_id,
        inventory_revision_id=project.revision_id,
        based_on_last_event_id=snapshot.last_event_id,
        event_id=event_id,
        evidence_id=evidence_id,
        geometry_basis_hash=geometry_basis(geometry),
        recorded_at=now,
        source_part_ids=geometry.active_part_ids,
        measurements=body.measurements,
    )
    evidence = Evidence(
        id=evidence_id,
        project_id=project.id,
        version_id=body.plan_version_id,
        kind="measurement",
        provenance="user",
        part_ids=geometry.active_part_ids,
        recorded_at=now,
        description="User-reported typed assembled stand/device mass, COM and support measurements; not a physical test or uncertainty guarantee",
        verification_state="user_confirmed",
    )
    event = PhysicalEvent(
        id=event_id,
        project_id=project.id,
        version_id=body.plan_version_id,
        kind="measurement",
        evidence_ids=(evidence_id,),
        recorded_at=now,
        actor="user",
        observation="Recorded typed mechanical measurements for portrait and landscape static tipping cases; no construction completion or physical pass",
        verification_state="user_confirmed",
    )
    connection.execute(
        "INSERT INTO stability_measurements VALUES (?, ?, ?, ?)",
        (record.id, project.id, body.plan_version_id, record.model_dump_json()),
    )
    connection.execute(
        "INSERT INTO progress_evidence VALUES (?, ?, ?, ?, ?)",
        (
            evidence.id,
            project.id,
            body.plan_version_id,
            None,
            evidence.model_dump_json(),
        ),
    )
    connection.execute(
        "INSERT INTO progress_events VALUES (?, ?, ?, ?)",
        (event.id, project.id, body.plan_version_id, event.model_dump_json()),
    )
    response = StabilityMeasurementResponse(
        project_id=project.id,
        plan_version_id=body.plan_version_id,
        inventory_revision_id=project.revision_id,
        last_event_id=event_id,
        measurement_id=record_id,
        evidence_id=evidence_id,
    )
    store.remember(
        connection,
        owner,
        scope,
        body.idempotency_key,
        hashed,
        response.model_dump(mode="json"),
    )
    return response


def measured_analysis(snapshot, geometry):
    """Return (input, policy, warnings), or None for missing/stale records.

    Never infer numbers from free text."""
    record = snapshot.measurements
    if record is None:
        return None
    if (
        record.project_id != snapshot.project.id
        or record.plan_version_id != snapshot.version.version_id
        or record.inventory_revision_id != snapshot.project.revision_id
        or record.event_id != snapshot.last_event_id
        or set(record.source_part_ids) != set(geometry.active_part_ids)
        or record.geometry_basis_hash != geometry_basis(geometry)
    ):
        return None
    if any(
        i.evidence_id == record.evidence_id
        and i.invalidated_for_version_id == record.plan_version_id
        for i in snapshot.evidence_invalidations
    ):
        return None
    evidence = next(
        (e for e in snapshot.history_evidence if e.id == record.evidence_id), None
    )
    event = snapshot.history_events[-1] if snapshot.history_events else None
    if (
        evidence is None
        or evidence.project_id != record.project_id
        or evidence.version_id != record.plan_version_id
        or evidence.kind != "measurement"
        or evidence.provenance != "user"
        or evidence.verification_state != "user_confirmed"
        or set(evidence.part_ids) != set(record.source_part_ids)
        or event is None
        or event.id != record.event_id
        or event.kind != "measurement"
        or event.actor != "user"
        or event.verification_state != "user_confirmed"
        or event.evidence_ids != (record.evidence_id,)
    ):
        return None
    data = record.measurements
    validate_contact(geometry, data)

    def quantity(value, unit, resolution, method):
        return dict(
            kind="scalar",
            value=float(value),
            unit=unit,
            provenance="measured",
            confirmed=True,
            evidence_ids=(record.evidence_id,),
            dependency_ids=(record.id,),
            uncertainty_notes=(
                f"User-reported method: {method}; instrument resolution {resolution} {unit}. Point estimate only; measurement uncertainty is not propagated into this scalar result.",
            ),
        )

    def body(body_id, measure, kind, parts):
        return dict(
            body_id=body_id,
            body_kind=kind,
            source_part_ids=parts,
            mass=quantity(
                measure.mass_kg, "kg", measure.mass_resolution_kg, measure.method
            ),
            center_of_mass={
                axis: quantity(
                    getattr(measure.center_of_mass_m, axis),
                    "m",
                    measure.position_resolution_m,
                    measure.method,
                )
                for axis in ("x", "y", "z")
            },
        )

    bodies = [body("measured-stand", data.stand, "stand_part", record.source_part_ids)]
    cases = []
    for case in data.cases:
        device_id = "device-" + case.orientation
        bodies.append(body(device_id, case.device, "device", ()))
        cases.append(
            dict(
                case_id=case.orientation,
                orientation=case.orientation + ": " + case.pose_description,
                body_ids=("measured-stand", device_id),
                contact_ids=("measured-base-contact",),
                gravity_m_s2=dict(
                    kind="scalar",
                    value=9.80665,
                    unit="m_s2",
                    provenance="assumed",
                    confirmed=False,
                    uncertainty_notes=(
                        "Conventional standard gravity assumed; local gravity not measured.",
                    ),
                ),
            )
        )
    support = data.support
    polygon = [
        dict(x=x, y=y, z=0.0)
        for x, y in (
            (support.x_min_m, support.y_min_m),
            (support.x_max_m, support.y_min_m),
            (support.x_max_m, support.y_max_m),
            (support.x_min_m, support.y_max_m),
        )
    ]
    identity = dict(
        project_id=record.project_id,
        plan_version_id=record.plan_version_id,
        inventory_revision=record.inventory_revision_id,
        history_cursor=snapshot.last_event_id,
        operation_state_id=record.event_id,
        canonical_geometry_hash=geometry.geometry_hash,
        evidence_hash=digest(record.model_dump(mode="json")),
        profile_hash=digest(
            [p.model_dump(mode="json") for p in snapshot.version.plan.joint_profiles]
        ),
    )
    analysis = StabilityInput.model_validate(
        dict(
            identity=identity,
            geometry_version=geometry.producer_version,
            profile_version="measured-point-v1",
            mechanical_snapshot=dict(
                bodies=bodies,
                contacts=[
                    dict(
                        contact_id="measured-base-contact",
                        body_id="measured-stand",
                        polygon_world=polygon,
                        active=True,
                        assumption_ids=("user-reported-contact",),
                    )
                ],
                rigid_assembly=True,
                horizontal_support=True,
                gravity_only=True,
                state_basis="observed",
                assumption_ids=(
                    "user-reported-measurements",
                    "stand-includes-all-parts-and-connectors",
                    "rigid-assembly-assumed",
                    "stationary-device-assumed",
                    "standard-gravity-assumed",
                    "point-estimates-not-uncertainty-bounds",
                ),
            ),
            cases=cases,
        )
    )
    policy = AnalysisPolicy(
        policy_id="measured-point-policy",
        version="v1",
        length_tolerance_m=1e-9,
        force_tolerance_n=1e-9,
        moment_tolerance_n_m=1e-9,
        relative_tolerance=1e-12,
        required_margin_m=data.required_margin_m,
        uncertainty_method="analytic_interval",
        evaluation_budget=2,
        required_check_types=("support", "tip"),
        required_case_ids=("portrait", "landscape"),
    )
    warnings = (
        "Scalar predictions use user-reported point measurements, not conservative uncertainty bounds. Instrument resolution is recorded but not propagated.",
        "Rigid assembly, stationary device and conventional standard gravity are assumptions. Phone retention, sliding and strength are not verified.",
        f"Actual support rectangle reported by user: {support.method}; resolution {support.resolution_m} m.",
    )
    return analysis, policy, warnings
