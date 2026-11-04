"""SYNTHETIC software fixtures only: no measured stock and no physical test."""

from datetime import UTC, datetime

from forma_compiler import CutProcess
from forma_renderer import StandParameters
from forma_synthesizer import MeasurementBasis, SearchInput

from forma_domain import models as m
from forma_domain.synthesis_contracts import SearchIdentity

PROJECT = "project-synth"
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def measured(value, unit="mm"):
    return m.Measurement(value=value, unit=unit, source="calculated", confirmed=True)


UNKNOWN = m.Measurement(value=None, unit="mm", source="unknown", confirmed=False)


def sheet(stock_id, width, height, thickness=2):
    return m.Stock(
        id=stock_id,
        kind="sheet",
        material="cardboard",
        condition="usable",
        width_mm=measured(width) if width else UNKNOWN,
        height_mm=measured(height) if height else UNKNOWN,
        thickness_mm=measured(thickness),
        remaining_length_mm=UNKNOWN,
        usable_regions=(
            m.Region(
                id=stock_id + "-region",
                geometry=m.Rect(x=0, y=0, width=width or 1, height=height or 1),
            ),
        ),
    )


def tape(stock_id="synthetic-tape-stock", length=500):
    return m.Stock(
        id=stock_id,
        kind="tape",
        material="other_supported",
        condition="usable",
        width_mm=measured(30),
        height_mm=UNKNOWN,
        thickness_mm=UNKNOWN,
        remaining_length_mm=measured(length) if length is not None else UNKNOWN,
    )


def evidence(project=PROJECT):
    return tuple(
        m.Evidence(
            id=name,
            project_id=project,
            version_id="synthetic-v1",
            kind="measurement",
            provenance="synthetic_fixture",
            recorded_at=NOW,
            description="SYNTHETIC software fixture only; no physical test",
            verification_state="unknown",
        )
        for name in ("synthetic-process", "synthetic-tape", "synthetic-fold")
    )


def profiles():
    return tuple(
        m.JointProfile(
            id=f"synthetic-{name}-profile",
            strategy=strategy,
            status="tested",
            material="cardboard",
            thickness_min_mm=1,
            thickness_max_mm=3,
            tolerated_error_mm=1,
            test_evidence_ids=(f"synthetic-{name}",),
            limitations=("SYNTHETIC only",),
        )
        for name, strategy in (("tape", "tape"), ("fold", "fold_brace"))
    )


def constraints(angle=60):
    return m.Constraints(
        device_mass_g=measured(180, "g"),
        support_angle_deg=measured(angle, "deg"),
        max_footprint_width_mm=measured(120),
        max_footprint_height_mm=measured(180),
    )


def parameters(project=PROJECT):
    return StandParameters(
        footprint_depth_mm=measured(140),
        lip_mm=measured(15),
        device_width_mm=measured(70),
        device_thickness_mm=measured(8),
        device_contact_height_mm=measured(100),
        tape_overlap_mm=measured(10),
        tools_confirmed=True,
        joint_access_confirmed=True,
        device_label="SYNTHETIC phone",
        test_duration_seconds=60,
        test_surface="SYNTHETIC desk",
        test_pass_criteria=("No slip or tip",),
        profile_evidence=evidence(project)[1:],
    )


def identity(**overrides):
    values = dict(
        project_id=PROJECT,
        inventory_revision_id="inventory-synth-1",
        active_version_id=None,
        last_event_id=None,
        context_fingerprint="0" * 64,
        measurement_record_ids=(),
    )
    values.update(overrides)
    return SearchIdentity(**values)


def search_input(
    stocks=None,
    measurements=(),
    tools=("SYNTHETIC ruler", "SYNTHETIC scissors", "SYNTHETIC knife"),
    **overrides,
):
    values = dict(
        identity=identity(
            measurement_record_ids=tuple(b.record_id for b in measurements)
        ),
        stocks=stocks
        if stocks is not None
        else (sheet("synthetic-sheet", 200, 550), tape()),
        constraints=constraints(),
        process=CutProcess(
            kerf_min_mm=2, edge_margin_min_mm=4, evidence=evidence()[:1]
        ),
        parameters=parameters(),
        joint_profiles=profiles(),
        kerf_mm=2,
        edge_margin_mm=4,
        declared_tools=tools,
        measurements=measurements,
        allow_synthetic=True,
    )
    values.update(overrides)
    return SearchInput(**values)


def measurement_basis():
    return MeasurementBasis(
        record_id="stability-measurement-1",
        plan_version_id="version-other",
        geometry_basis_hash="a" * 64,
    )
