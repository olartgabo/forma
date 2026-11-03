"""Analytic constitutive references; these are synthetic, not material tests."""

import copy

import pytest
from forma_stability import evaluate_stability
from pydantic import ValidationError
from test_engine import policy, q, request

from forma_domain.stability_contracts import StabilityInput


def packet():
    data = request()
    data["cases"][0].update(
        sliding=dict(
            contact_id="contact",
            normal_force_n=q(10, "N"),
            tangential_force_n=q(2, "N"),
            friction_coefficient=q(0.3, "1"),
            planar_coulomb_applicable=True,
        ),
        joint_demands=[
            dict(
                joint_id="joint-a",
                demand_n=q(2, "N"),
                allowable_n=q(3, "N"),
                capacity_basis="SYNTHETIC single-mode allowable, not a tested joint",
                scalar_mode_applicable=True,
            )
        ],
        deformation=dict(
            member_id="part",
            support_model="cantilever_end_load",
            force_n=q(1, "N"),
            length_m=q(0.1),
            elastic_modulus_pa=q(1e9, "Pa"),
            second_moment_m4=q(1e-10, "m4"),
            allowable_deflection_m=q(0.004),
            linear_elastic_small_deflection_applicable=True,
        ),
    )
    return data


def run(data=None, **changes):
    return evaluate_stability(
        StabilityInput.model_validate(data or packet()),
        policy(
            required_check_types=["support", "tip", "slide", "joint", "deformation"],
            **changes,
        ),
    )


def check(report, kind):
    return next(r for r in report.results if r.check_type == kind)


def test_analytic_coulomb_beam_and_joint_comparisons_do_not_fake_tipping():
    report = run()
    assert check(report, "slide").status == "modeled_pass"
    assert check(report, "slide").quantities[-1].value == pytest.approx(3)
    assert check(report, "joint").status == "modeled_pass"
    assert check(report, "deformation").status == "modeled_pass"
    assert check(report, "deformation").quantities[-1].value == pytest.approx(1 / 300)
    assert check(report, "tip").status == "unsupported"
    assert report.status == "unsupported"
    assert report.physical_evidence_ids == ()


def test_boundary_failures_and_numeric_tolerance():
    data = packet()
    case = data["cases"][0]
    case["sliding"]["tangential_force_n"] = q(3, "N")
    assert check(run(data), "slide").status == "indeterminate"
    case["sliding"]["tangential_force_n"] = q(3.01, "N")
    assert check(run(data, force_tolerance_n=0.02), "slide").status == "indeterminate"
    assert check(run(data), "slide").status == "modeled_fail"
    case["joint_demands"][0]["demand_n"] = q(4, "N")
    case["deformation"]["allowable_deflection_m"] = q(0.001)
    report = run(data)
    assert check(report, "joint").status == "modeled_fail"
    assert check(report, "deformation").status == "modeled_fail"
    assert report.status == "modeled_fail"


def test_beam_support_condition_and_linear_scaling():
    data = packet()
    reference = check(run(data), "deformation").quantities[-1].value
    beam = data["cases"][0]["deformation"]
    beam["force_n"] = q(2, "N")
    assert check(run(data), "deformation").quantities[-1].value == pytest.approx(
        2 * reference
    )
    beam["elastic_modulus_pa"] = q(2e9, "Pa")
    assert check(run(data), "deformation").quantities[-1].value == pytest.approx(
        reference
    )
    beam["support_model"] = "simply_supported_center_load"
    assert check(run(data), "deformation").quantities[-1].value == pytest.approx(
        reference / 16
    )


@pytest.mark.parametrize(
    "field,kind,quantity",
    [
        ("sliding", "slide", "friction_coefficient"),
        ("deformation", "deformation", "elastic_modulus_pa"),
    ],
)
def test_unknown_interval_applicability_and_identity(field, kind, quantity):
    data = packet()
    old_hash = run(data).cache_hash
    original = data["cases"][0][field][quantity]
    data["cases"][0][field][quantity] = dict(
        kind="unknown", unit=original["unit"], provenance="unknown", confirmed=False
    )
    report = run(data)
    assert check(report, kind).status == "needs_measurement"
    assert report.cache_hash != old_hash
    data["cases"][0][field][quantity] = dict(
        kind="interval",
        lower=1.0,
        upper=2.0,
        unit=original["unit"],
        provenance="specified",
        confirmed=False,
    )
    assert check(run(data), kind).status == "indeterminate"


def test_missing_checks_future_inactive_contact_and_budget_never_pass():
    report = run(request())
    assert all(
        check(report, k).status == "needs_measurement"
        for k in ("slide", "joint", "deformation")
    )
    data = packet()
    data["mechanical_snapshot"]["contacts"][0]["active"] = False
    assert check(run(data), "slide").status == "needs_measurement"
    data["mechanical_snapshot"]["bodies"][0]["state"] = "future"
    assert all(
        check(run(data), k).status == "unsupported"
        for k in ("slide", "joint", "deformation")
    )
    data = packet()
    second = copy.deepcopy(data["cases"][0])
    second["case_id"] = "z-case"
    data["cases"].append(second)
    report = run(data, evaluation_budget=1)
    assert all(
        r.computation == "budget_exhausted" and r.status == "indeterminate"
        for r in report.results
        if r.case_id == "z-case"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("elastic_modulus_pa", q(0, "Pa")),
        ("second_moment_m4", q(1, "m3")),
        ("length_m", q(-1)),
        ("force_n", q(float("inf"), "N")),
    ],
)
def test_invalid_units_nonfinite_and_sign_rejected(field, value):
    data = packet()
    data["cases"][0]["deformation"][field] = value
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)


def test_overflow_and_outside_linear_model_cannot_pass():
    data = packet()
    beam = data["cases"][0]["deformation"]
    beam["force_n"] = q(10, "N")
    assert check(run(data), "deformation").status == "unsupported"
    beam["elastic_modulus_pa"] = q(1e308, "Pa")
    report = run(data)
    assert check(report, "deformation").status == "indeterminate"
    assert check(report, "deformation").computation == "numerical_failure"


def test_all_joint_modes_checked_and_wrong_member_or_contact_rejected():
    data = packet()
    second = copy.deepcopy(data["cases"][0]["joint_demands"][0])
    second.update(joint_id="joint-b", demand_n=q(10, "N"))
    data["cases"][0]["joint_demands"].append(second)
    assert check(run(data), "joint").status == "modeled_fail"
    data["cases"][0]["deformation"]["member_id"] = "missing"
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)


def test_zero_demand_does_not_substitute_for_unknown_friction():
    data = packet()
    sliding = data["cases"][0]["sliding"]
    sliding["tangential_force_n"] = q(0, "N")
    sliding["friction_coefficient"] = dict(
        kind="unknown", unit="1", provenance="unknown", confirmed=False
    )
    assert check(run(data), "slide").status == "needs_measurement"
    sliding["friction_coefficient"] = q(0.3, "1")
    sliding["normal_force_n"] = q(0, "N")
    assert check(run(data), "slide").status == "unsupported"
    data = packet()
    data["cases"][0]["sliding"]["contact_id"] = "missing"
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)
