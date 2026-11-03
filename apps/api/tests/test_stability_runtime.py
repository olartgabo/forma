"""Analytic labeled software fixture, never a physical pass or pose producer."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from forma_api import stability_runtime as r
from forma_api.plans import PlanService
from forma_api.progress import snapshot
from forma_api.projects import ProjectStore
from forma_domain.models import Evidence
from forma_domain.stability_contracts import AnalysisPolicy, StabilityInput

pytest_plugins = ["test_stability_route"]


def analytic(s, unknown=False):
    def q(value, unit):
        return dict(
            kind="scalar",
            value=float(value),
            unit=unit,
            provenance="assumed",
            confirmed=False,
        )

    identity = dict(
        project_id=s.project.id,
        plan_version_id=s.version.version_id,
        inventory_revision=s.project.revision_id,
        history_cursor=s.last_event_id,
        operation_state_id="analytic-state",
        canonical_geometry_hash="a" * 64,
        evidence_hash="b" * 64,
        profile_hash="c" * 64,
    )
    mass = (
        dict(kind="unknown", unit="kg", provenance="unknown", confirmed=False)
        if unknown
        else q(1, "kg")
    )
    analysis = StabilityInput.model_validate(
        dict(
            identity=identity,
            geometry_version="analytic-v1",
            profile_version="analytic-v1",
            mechanical_snapshot=dict(
                bodies=[
                    dict(
                        body_id="analytic-body",
                        source_part_ids=[s.version.plan.parts[0].id],
                        mass=mass,
                        center_of_mass=dict(x=q(0, "m"), y=q(0, "m"), z=q(0.1, "m")),
                    )
                ],
                contacts=[
                    dict(
                        contact_id="analytic-contact",
                        body_id="analytic-body",
                        active=True,
                        polygon_world=[
                            dict(x=x, y=y, z=0.0)
                            for x, y in [
                                (-1.0, -1.0),
                                (1.0, -1.0),
                                (1.0, 1.0),
                                (-1.0, 1.0),
                            ]
                        ],
                    )
                ],
                rigid_assembly=True,
                horizontal_support=True,
                gravity_only=True,
                state_basis="nominal",
                assumption_ids=["analytic-only"],
            ),
            cases=[
                dict(
                    case_id="analytic-load",
                    orientation="Analytic upright",
                    body_ids=["analytic-body"],
                    contact_ids=["analytic-contact"],
                    gravity_m_s2=q(9.81, "m_s2"),
                )
            ],
        )
    )
    policy = AnalysisPolicy(
        policy_id="analytic-policy",
        version="v1",
        length_tolerance_m=0.001,
        force_tolerance_n=0.01,
        moment_tolerance_n_m=0.001,
        relative_tolerance=0.001,
        required_margin_m=0.002,
        uncertainty_method="analytic_interval",
        evaluation_budget=100,
        required_check_types=("tip",),
        required_case_ids=("analytic-load",),
    )
    return r.ResolvedStability(analysis, policy)


def authorized(connected):
    _, url, payload, directory = connected
    project_id = url.split("/")[2]
    store = ProjectStore(directory)
    with store.transaction() as db:
        project = store.read(db, "alice", project_id)
        version = PlanService(store).read(db, project_id, payload["plan_version_id"])
        return r.StabilitySnapshot(
            project, version, snapshot(db, version.plan), None, (), ()
        )


def test_analytic_computed_report_and_unknown_mass(connected):
    s = authorized(connected)
    result = r.analyze(s, analytic)
    assert result.status == "complete"
    assert result.report.status == "modeled_pass"
    assert result.report.input_warnings
    unknown = r.analyze(s, lambda s: analytic(s, unknown=True))
    assert unknown.status != "complete"
    assert unknown.report.status != "modeled_pass"
    assert (
        analytic(s, True).analysis.mechanical_snapshot.bodies[0].mass.kind == "unknown"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "foreign"),
        ("plan_version_id", "foreign"),
        ("inventory_revision", "stale"),
        ("history_cursor", "stale"),
    ],
)
def test_resolver_cannot_substitute_identity(connected, field, value):
    s = authorized(connected)
    resolved = analytic(s)
    analysis = resolved.analysis.model_copy(
        update={
            "identity": resolved.analysis.identity.model_copy(update={field: value})
        }
    )
    with pytest.raises(ValueError, match="identity"):
        r.analyze(s, lambda _: r.ResolvedStability(analysis, resolved.policy))


def test_resolver_cannot_substitute_part(connected):
    s = authorized(connected)
    resolved = analytic(s)
    data = resolved.analysis.model_dump()
    data["mechanical_snapshot"]["bodies"][0]["source_part_ids"] = ("foreign-part",)
    with pytest.raises(ValueError, match="parts"):
        r.analyze(
            s,
            lambda _: r.ResolvedStability(
                StabilityInput.model_validate(data), resolved.policy
            ),
        )


def test_resolver_cannot_use_unscoped_measurement_evidence(connected):
    s = authorized(connected)
    resolved = analytic(s)
    data = resolved.analysis.model_dump()
    data["mechanical_snapshot"]["bodies"][0]["mass"].update(
        provenance="measured", confirmed=True, evidence_ids=("foreign-evidence",)
    )
    with pytest.raises(ValueError, match="evidence"):
        r.analyze(
            s,
            lambda _: r.ResolvedStability(
                StabilityInput.model_validate(data), resolved.policy
            ),
        )


@pytest.mark.parametrize(
    "evidence_change",
    [
        {
            "kind": "model_interpretation",
            "provenance": "model",
            "verification_state": "unknown",
        },
        {"kind": "photo"},
        {"part_ids": ("foreign-part",)},
        {"version_id": "prior-version"},
        {"verification_state": "unknown"},
        {},
    ],
)
@pytest.mark.parametrize("field", ["mass", "com", "gravity"])
def test_generic_evidence_never_authenticates_measurement(
    connected, evidence_change, field
):
    s = authorized(connected)
    resolved = analytic(s)
    evidence = Evidence(
        id="measurement-record",
        project_id=s.project.id,
        version_id=s.version.version_id,
        kind="measurement",
        provenance="user",
        recorded_at=datetime.now(UTC),
        description="Analytic description is not a typed measurement",
        verification_state="user_confirmed",
    ).model_copy(update=evidence_change)
    s = replace(s, history_evidence=(evidence,))
    data = resolved.analysis.model_dump()
    body = data["mechanical_snapshot"]["bodies"][0]
    quantity = (
        body["mass"]
        if field == "mass"
        else body["center_of_mass"]["x"]
        if field == "com"
        else data["cases"][0]["gravity_m_s2"]
    )
    quantity.update(provenance="measured", confirmed=True, evidence_ids=(evidence.id,))
    with pytest.raises(ValueError):
        r.analyze(
            s,
            lambda _: r.ResolvedStability(
                StabilityInput.model_validate(data), resolved.policy
            ),
        )


def test_specified_confirmed_cannot_bypass_missing_measurement_binding(connected):
    s = authorized(connected)
    resolved = analytic(s)
    data = resolved.analysis.model_dump()
    data["mechanical_snapshot"]["bodies"][0]["mass"].update(
        provenance="specified", confirmed=True
    )
    with pytest.raises(ValueError, match="Typed measurement"):
        r.analyze(
            s,
            lambda _: r.ResolvedStability(
                StabilityInput.model_validate(data), resolved.policy
            ),
        )
