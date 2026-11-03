"""Contract validation only: no fixture establishes a physical result."""

import pytest
from pydantic import ValidationError

from forma_domain.stability_contracts import (
    AnalysisIdentity,
    AnalysisPolicy,
    CheckResult,
    QuantityEstimate,
    StabilityReport,
)


def identity():
    return AnalysisIdentity(
        project_id="project",
        plan_version_id="v1",
        inventory_revision="inv1",
        history_cursor="history1",
        operation_state_id="state1",
        **{
            name: "a" * 64
            for name in (
                "canonical_geometry_hash",
                "evidence_hash",
                "profile_hash",
            )
        },
    )


def policy():
    return AnalysisPolicy(
        policy_id="policy",
        version="v1",
        length_tolerance_m=0.001,
        force_tolerance_n=0.01,
        moment_tolerance_n_m=0.001,
        relative_tolerance=0.001,
        required_margin_m=0.002,
        uncertainty_method="analytic_interval",
        evaluation_budget=100,
        required_check_types=("tip",),
        required_case_ids=("load",),
    )


def result(**changes):
    data = dict(
        case_id="load",
        check_type="tip",
        status="modeled_pass",
        computation="complete",
        explanation="Modeled within explicit policy",
    )
    return CheckResult(**(data | changes))


def report(**changes):
    data = dict(
        identity=identity(),
        report_version="v1",
        engine_version="s0",
        geometry_version="v1",
        profile_version="v1",
        cache_hash="b" * 64,
        policy=policy(),
        status="modeled_pass",
        coverage="complete",
        results=(result(),),
    )
    return StabilityReport(**(data | changes))


def test_quantity_shapes_round_trip_and_keep_dependencies():
    q = QuantityEstimate(
        kind="interval",
        unit="kg",
        lower=0.1,
        upper=0.3,
        provenance="assumed",
        confirmed=False,
        dependency_ids=("mass",),
        correlation_group_ids=("shared_density",),
        uncertainty_notes=("Unmeasured",),
    )
    assert QuantityEstimate.model_validate_json(q.model_dump_json()) == q
    assert q.lower == 0.1 and q.upper == 0.3
    scalar = QuantityEstimate(
        kind="scalar",
        unit="m",
        value=0.2,
        provenance="measured",
        confirmed=True,
        evidence_ids=("ruler",),
    )
    assert scalar.value == 0.2
    with pytest.raises(ValidationError):
        q.lower = 0.0


def test_unknown_preserved_without_substituting_zero():
    q = QuantityEstimate(
        kind="unknown",
        unit="kg",
        provenance="unknown",
        confirmed=False,
        dependency_ids=("unweighed_device",),
    )
    restored = QuantityEstimate.model_validate_json(q.model_dump_json())
    assert restored.value is None and restored.lower is None and restored.upper is None
    r = report(
        status="needs_measurement",
        results=(
            result(
                status="needs_measurement",
                computation="not_run",
                quantities=(q,),
                unresolved_predicates=("Measure device mass",),
            ),
        ),
        unresolved_predicates=("Measure device mass",),
    )
    assert r.status == "needs_measurement"


@pytest.mark.parametrize(
    "changes",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": -float("inf")},
        {"value": True},
        {"value": "0.2"},
        {"lower": 0.1},
        {"provenance": "unknown"},
        {"provenance": "assumed", "confirmed": True},
        {"unit": "mm"},
        {"extra": 1},
        {"kind": "interval", "value": None, "lower": 2.0, "upper": 1.0},
        {"kind": "interval", "value": None, "lower": 0.0},
        {"kind": "unknown"},
        {"provenance": "measured"},
    ],
)
def test_reject_malformed_quantities(changes):
    data = dict(
        kind="scalar", unit="m", value=0.2, provenance="specified", confirmed=False
    )
    with pytest.raises(ValidationError):
        QuantityEstimate(**(data | changes))


def test_identity_requires_all_exact_hashes():
    data = identity().model_dump()
    for key in (k for k in data if k.endswith("_hash")):
        with pytest.raises(ValidationError):
            AnalysisIdentity(**(data | {key: "unknown"}))
        with pytest.raises(ValidationError):
            AnalysisIdentity(**{k: v for k, v in data.items() if k != key})


@pytest.mark.parametrize(
    "changes",
    [
        {"required_margin_m": -0.1},
        {"relative_tolerance": float("nan")},
        {"length_tolerance_m": -0.001},
        {"required_case_ids": ()},
        {"required_check_types": ("tip", "tip")},
        {"required_case_ids": ("load", "load")},
    ],
)
def test_policy_rejects_invalid_or_ambiguous_requirements(changes):
    with pytest.raises(ValidationError):
        AnalysisPolicy(**(policy().model_dump() | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"computation": "numerical_failure"},
        {"computation": "not_run"},
        {"unresolved_predicates": ("Unknown friction",)},
        {"status": "unsupported", "computation": "numerical_failure"},
        {"status": "not_applicable"},
        {
            "quantities": (
                QuantityEstimate(
                    kind="unknown", unit="1", provenance="unknown", confirmed=False
                ),
            )
        },
    ],
)
def test_check_cannot_turn_uncertainty_or_computation_failure_into_pass(changes):
    with pytest.raises(ValidationError):
        result(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"results": ()},
        {"coverage": "partial"},
        {"results": (result(), result())},
        {"unresolved_predicates": ("Surface unknown",)},
        {"results": (result(status="indeterminate", computation="numerical_failure"),)},
        {"results": (result(status="unsupported", computation="not_run"),)},
        {"results": (result(status="not_applicable", computation="not_run"),)},
        {"results": (result(status="modeled_fail"),)},
        {"status": "modeled_fail"},
    ],
)
def test_report_rejects_false_aggregate(changes):
    with pytest.raises(ValidationError):
        report(**changes)


def test_missing_required_case_cannot_be_hidden_by_another_case():
    with pytest.raises(ValidationError):
        report(results=(result(case_id="other"),))
    partial = report(status="indeterminate", coverage="partial", results=())
    assert partial.results == ()


def test_failed_computation_and_failed_check_remain_distinct():
    failed = report(status="modeled_fail", results=(result(status="modeled_fail"),))
    assert failed.results[0].computation == "complete"
    unknown = report(
        status="indeterminate",
        results=(result(status="indeterminate", computation="numerical_failure"),),
    )
    assert unknown.status == "indeterminate"


def test_modeled_pass_and_physical_references_never_claim_physical_success():
    r = report(physical_evidence_ids=("test_photo",))
    assert r.status == "modeled_pass"
    assert "physical_pass" not in r.model_dump()
    with pytest.raises(ValidationError):
        StabilityReport(**(r.model_dump() | {"status": "physical_pass"}))
    with pytest.raises(ValidationError):
        StabilityReport(**(r.model_dump() | {"physical_pass": True}))


def test_required_failure_cannot_be_hidden_as_indeterminate():
    with pytest.raises(ValidationError):
        report(status="indeterminate", results=(result(status="modeled_fail"),))


@pytest.mark.parametrize(
    "changes",
    [
        {"evaluation_budget": 0},
        {"evaluation_budget": True},
        {"required_case_ids": tuple(f"case{i}" for i in range(17))},
    ],
)
def test_policy_bounds(changes):
    with pytest.raises(ValidationError):
        AnalysisPolicy(**(policy().model_dump() | changes))


def test_empty_history_cursor_is_explicit_and_required():
    data = identity().model_dump()
    assert AnalysisIdentity(**(data | {"history_cursor": None})).history_cursor is None
    with pytest.raises(ValidationError):
        AnalysisIdentity(**{k: v for k, v in data.items() if k != "history_cursor"})


def test_uncertainty_method_cannot_claim_a_bound_from_sampling():
    for method in ("interval", "bounded_sampling"):
        with pytest.raises(ValidationError):
            AnalysisPolicy(**(policy().model_dump() | {"uncertainty_method": method}))
