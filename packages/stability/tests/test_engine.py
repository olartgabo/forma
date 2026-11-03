"""Analytic reference mathematics only; no physical measurements or test passes."""

import copy
import math

import pytest
from forma_stability import evaluate_stability
from pydantic import ValidationError

from forma_domain.stability_contracts import AnalysisPolicy, StabilityInput


def q(value, unit="m"):
    return dict(
        kind="scalar",
        value=float(value),
        unit=unit,
        provenance="specified",
        confirmed=False,
    )


def request(x=0.5, y=0.5):
    identity = dict(
        project_id="project",
        plan_version_id="v1",
        inventory_revision="inv1",
        history_cursor=None,
        operation_state_id="state",
        canonical_geometry_hash="a" * 64,
        evidence_hash="b" * 64,
        profile_hash="c" * 64,
    )
    body = dict(
        body_id="body",
        source_part_ids=["part"],
        mass=q(2, "kg"),
        center_of_mass=dict(x=q(x), y=q(y), z=q(1)),
    )
    contact = dict(
        contact_id="contact",
        body_id="body",
        active=True,
        polygon_world=[
            dict(x=float(x), y=float(y), z=0.0)
            for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
        ],
    )
    return dict(
        identity=identity,
        geometry_version="v1",
        profile_version="v1",
        mechanical_snapshot=dict(
            bodies=[body],
            contacts=[contact],
            rigid_assembly=True,
            horizontal_support=True,
            gravity_only=True,
            state_basis="nominal",
        ),
        cases=[
            dict(
                case_id="case",
                orientation="portrait",
                body_ids=["body"],
                contact_ids=["contact"],
                gravity_m_s2=q(10, "m_s2"),
            )
        ],
    )


def policy(**changes):
    data = dict(
        policy_id="policy",
        version="v1",
        length_tolerance_m=1e-8,
        force_tolerance_n=0.0,
        moment_tolerance_n_m=0.0,
        relative_tolerance=0.0,
        required_margin_m=0.0,
        uncertainty_method="analytic_interval",
        evaluation_budget=100,
        required_check_types=["tip"],
        required_case_ids=["case"],
    )
    return AnalysisPolicy(**(data | changes))


def run(data=None, **changes):
    return evaluate_stability(
        StabilityInput.model_validate(data or request()), policy(**changes)
    )


@pytest.mark.parametrize(
    "x,status,margin",
    [
        (0.5, "modeled_pass", 0.5),
        (0, "indeterminate", 0),
        (-0.1, "modeled_fail", -0.1),
        (1.1, "modeled_fail", -0.1),
    ],
)
def test_rectangle_signed_edges(x, status, margin):
    report = run(request(x=x))
    assert report.status == status
    assert report.overlays[0].signed_margin_m == pytest.approx(margin)
    assert report.overlays[0].restoring_moment_n_m == pytest.approx(20 * margin)
    assert report.physical_evidence_ids == ()


def test_triangle_diagonal_and_clearance_policy():
    data = request(0.25, 0.25)
    data["mechanical_snapshot"]["contacts"][0]["polygon_world"].pop(2)
    report = run(data)
    assert report.overlays[0].signed_margin_m == pytest.approx(0.25)
    assert run(data, required_margin_m=0.3).status == "modeled_fail"
    assert run(data, required_margin_m=0.25).status == "indeterminate"
    assert run(request(x=1e-9)).status == "indeterminate"


def test_weighted_mass_translation_rotation_scale():
    data = request(0.25, 0.5)
    other = copy.deepcopy(data["mechanical_snapshot"]["bodies"][0])
    other.update(
        body_id="payload",
        source_part_ids=["phone"],
        mass=q(6, "kg"),
        center_of_mass=dict(x=q(0.75), y=q(0.5), z=q(2)),
    )
    data["mechanical_snapshot"]["bodies"].append(other)
    data["cases"][0]["body_ids"].append("payload")
    report = run(data)
    assert report.overlays[0].center_of_mass.x == pytest.approx(0.625)
    assert report.overlays[0].signed_margin_m == pytest.approx(0.375)
    for body in data["mechanical_snapshot"]["bodies"]:
        com = body["center_of_mass"]
        x, y = com["x"]["value"], com["y"]["value"]
        com["x"] = q(10 - 2 * y)
        com["y"] = q(20 + 2 * x)
    for point in data["mechanical_snapshot"]["contacts"][0]["polygon_world"]:
        x, y = point["x"], point["y"]
        point["x"], point["y"] = 10 - 2 * y, 20 + 2 * x
    transformed = run(data)
    assert transformed.overlays[0].signed_margin_m == pytest.approx(0.75)
    assert transformed.overlays[0].restoring_moment_n_m == pytest.approx(60)


@pytest.mark.parametrize("field", ["mass", "x", "y", "z", "gravity"])
@pytest.mark.parametrize(
    "kind,status", [("unknown", "needs_measurement"), ("interval", "indeterminate")]
)
def test_uncertainty_never_sample_pass(field, kind, status):
    data = request()
    body = data["mechanical_snapshot"]["bodies"][0]
    old = (
        body["mass"]
        if field == "mass"
        else data["cases"][0]["gravity_m_s2"]
        if field == "gravity"
        else body["center_of_mass"][field]
    )
    old.pop("value")
    old["kind"] = kind
    if kind == "unknown":
        old["provenance"] = "unknown"
    else:
        old.update(lower=0.1, upper=2.0)
    assert run(data).status == status
    assert not run(data).overlays


@pytest.mark.parametrize(
    "change,status",
    [
        ("inactive", "needs_measurement"),
        ("future", "unsupported"),
        ("rigid_assembly", "unsupported"),
        ("gravity_only", "unsupported"),
        ("horizontal_support", "unsupported"),
        ("nonplanar", "unsupported"),
        ("degenerate", "indeterminate"),
        ("crossing", "indeterminate"),
    ],
)
def test_unsupported_and_invalid_geometry(change, status):
    data = request()
    snap = data["mechanical_snapshot"]
    contact = snap["contacts"][0]
    if change == "inactive":
        contact["active"] = False
    elif change == "future":
        snap["bodies"][0]["state"] = "future"
    elif change == "nonplanar":
        contact["polygon_world"][0]["z"] = 0.1
    elif change == "degenerate":
        contact["polygon_world"] = [dict(x=float(i), y=0.0, z=0.0) for i in range(3)]
    elif change == "crossing":
        contact["polygon_world"][1], contact["polygon_world"][2] = (
            contact["polygon_world"][2],
            contact["polygon_world"][1],
        )
    else:
        snap[change] = False
    assert run(data).status == status


def test_required_matrix_named_cases_and_unsupported_checks():
    data = request()
    other = copy.deepcopy(data["cases"][0])
    other.update(case_id="landscape", orientation="landscape")
    data["cases"].append(other)
    report = run(data, required_case_ids=["case", "landscape"])
    assert report.status == "modeled_pass"
    assert [(o.case_id, o.orientation) for o in report.overlays] == [
        ("case", "portrait"),
        ("landscape", "landscape"),
    ]
    assert run(data, required_case_ids=["case", "missing"]).status == "indeterminate"
    assert (
        run(data, required_check_types=["tip", "slide", "joint", "deformation"]).status
        == "needs_measurement"
    )


@pytest.mark.parametrize(
    "change", ["mass", "source", "reference", "duplicate", "nan", "unit"]
)
def test_contract_rejects_invalid_input(change):
    data = request()
    body = data["mechanical_snapshot"]["bodies"][0]
    if change == "mass":
        body["mass"]["value"] = 0.0
    elif change == "source":
        other = copy.deepcopy(body)
        other["body_id"] = "other"
        data["mechanical_snapshot"]["bodies"].append(other)
    elif change == "reference":
        data["cases"][0]["body_ids"] = ["absent"]
    elif change == "duplicate":
        data["cases"].append(copy.deepcopy(data["cases"][0]))
    elif change == "nan":
        body["center_of_mass"]["x"]["value"] = math.nan
    else:
        body["mass"]["unit"] = "m"
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)


def test_hash_binds_identity_geometry_policy_and_is_order_independent():
    data = request()
    base = run(data).cache_hash
    assert base == run(data).cache_hash
    assert base != run(data, required_margin_m=0.1).cache_hash
    for target, key, value in [
        (data["identity"], "history_cursor", "history"),
        (data["mechanical_snapshot"]["bodies"][0]["mass"], "value", 3.0),
        (data["cases"][0], "orientation", "landscape"),
    ]:
        saved = target[key]
        target[key] = value
        assert base != run(data).cache_hash
        target[key] = saved
    other = copy.deepcopy(data["mechanical_snapshot"]["bodies"][0])
    other.update(body_id="other", source_part_ids=["part2"])
    data["mechanical_snapshot"]["bodies"].append(other)
    data["cases"][0]["body_ids"].append("other")
    first = run(data).cache_hash
    data["mechanical_snapshot"]["bodies"].reverse()
    data["cases"][0]["body_ids"].reverse()
    assert first == run(data).cache_hash


def test_multiple_contacts_order_and_dependency_versions(monkeypatch):
    import forma_stability

    data = request()
    second = copy.deepcopy(data["mechanical_snapshot"]["contacts"][0])
    second["contact_id"] = "contact2"
    data["mechanical_snapshot"]["contacts"].append(second)
    data["cases"][0]["contact_ids"].append("contact2")
    before = run(data)
    data["mechanical_snapshot"]["contacts"].reverse()
    data["cases"][0]["contact_ids"].reverse()
    after = run(data)
    assert before.cache_hash == after.cache_hash
    assert before.overlays == after.overlays
    monkeypatch.setattr(forma_stability, "ENGINE_VERSION", "s1-test")
    assert before.cache_hash != run(data).cache_hash
    monkeypatch.setattr(forma_stability.np, "__version__", "test-version")
    assert after.cache_hash != run(data).cache_hash


def test_numeric_failure_cannot_create_decisive_report():
    data = request()
    data["mechanical_snapshot"]["bodies"][0]["mass"]["value"] = 1e308
    assert run(data).status == "indeterminate"
    assert all(
        result.computation == "numerical_failure" for result in run(data).results
    )
    assert not run(data).overlays


def test_known_assumptions_do_not_claim_confirmed_measurements():
    data = request()
    data["mechanical_snapshot"]["bodies"][0]["mass"]["provenance"] = "assumed"
    assert run(data).status == "modeled_pass"
    assert run(data).physical_evidence_ids == ()
    data["mechanical_snapshot"]["bodies"][0]["mass"]["confirmed"] = True
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)


def test_budget_device_assumptions_and_declared_cases():
    data = request()
    device = copy.deepcopy(data["mechanical_snapshot"]["bodies"][0])
    device.update(body_id="phone", body_kind="device", source_part_ids=[])
    data["mechanical_snapshot"]["bodies"].append(device)
    data["cases"][0]["body_ids"].append("phone")
    data["mechanical_snapshot"]["assumption_ids"] = ["rigid"]
    data["mechanical_snapshot"]["contacts"][0]["assumption_ids"] = ["flat"]
    second = copy.deepcopy(data["cases"][0])
    second.update(case_id="second", orientation="landscape")
    data["cases"].append(second)
    report = run(data, evaluation_budget=1)
    assert report.status == "indeterminate"
    assert any(
        r.case_id == "second" and r.computation == "budget_exhausted"
        for r in report.results
    )
    assert report.assumption_ids == ("flat", "rigid")
    assert report.state_basis == "nominal"
    assert any(
        "phone mass: specified, confirmed=False" == text
        for text in report.input_warnings
    )
    assert len(run(data).overlays) == 2
    device["source_part_ids"] = ["invented"]
    with pytest.raises(ValidationError):
        StabilityInput.model_validate(data)


def test_invalid_polygon_has_invalid_input_computation():
    data = request()
    polygon = data["mechanical_snapshot"]["contacts"][0]["polygon_world"]
    polygon[1], polygon[2] = polygon[2], polygon[1]
    report = run(data)
    assert report.status == "indeterminate"
    assert all(r.computation == "invalid_input" for r in report.results)
