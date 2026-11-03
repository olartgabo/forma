"""Bounded scalar constitutive checks, independent of load-path reconstruction.

Coulomb: https://openstax.org/books/college-physics-2e/pages/5-1-friction
Euler-Bernoulli: MIT 2.080J Structural Mechanics, Lecture 8 (2013).
The caller supplies applicability, material values, demands and allowables. No
calibration, reaction distribution or engineering safety factor is invented.
"""

import math

from forma_domain.stability_contracts import CheckResult, QuantityEstimate


def quantities_for_case(case):
    """All additional quantities, for adapter provenance checks and diagnostics."""
    values = []
    if case.sliding is not None:
        values.extend(
            (
                case.sliding.normal_force_n,
                case.sliding.tangential_force_n,
                case.sliding.friction_coefficient,
            )
        )
    for joint in case.joint_demands:
        values.extend((joint.demand_n, joint.allowable_n))
    if case.deformation is not None:
        beam = case.deformation
        values.extend(
            (
                beam.force_n,
                beam.length_m,
                beam.elastic_modulus_pa,
                beam.second_moment_m4,
                beam.allowable_deflection_m,
            )
        )
    return tuple(values)


def _derived(value, unit):
    if not math.isfinite(value):
        raise FloatingPointError("Nonfinite constitutive result")
    return QuantityEstimate(
        kind="scalar", value=value, unit=unit, provenance="derived", confirmed=False
    )


def _compare(capacity, demand, tolerance, relative):
    band = max(tolerance, relative * max(abs(capacity), abs(demand)))
    delta = capacity - demand
    if not math.isfinite(delta) or not math.isfinite(band):
        raise FloatingPointError("Nonfinite comparison")
    return (
        "modeled_pass"
        if delta > band
        else "modeled_fail"
        if delta < -band
        else "indeterminate"
    )


def evaluate_physical_check(analysis, case, policy, check):
    def result(status, explanation, quantities=(), computation="complete"):
        return CheckResult(
            case_id=case.case_id,
            check_type=check,
            status=status,
            explanation=explanation,
            quantities=tuple(quantities),
            computation=computation,
            unresolved_predicates=()
            if status in ("modeled_pass", "modeled_fail")
            else (explanation,),
        )

    if any(
        b.state != "present"
        for b in analysis.mechanical_snapshot.bodies
        if b.body_id in case.body_ids
    ):
        return result(
            "unsupported",
            "Future bodies cannot support a current physical check",
            computation="not_run",
        )
    if check == "slide":
        item = case.sliding
        if item is None:
            return result(
                "needs_measurement",
                "Supply contact reaction demands and static friction coefficient",
                computation="not_run",
            )
        contact = next(
            c
            for c in analysis.mechanical_snapshot.contacts
            if c.contact_id == item.contact_id
        )
        if not contact.active:
            return result(
                "needs_measurement",
                "Sliding requires an active contact",
                computation="not_run",
            )
        if not item.planar_coulomb_applicable:
            return result(
                "unsupported",
                "Requires declared single-interface planar Coulomb applicability",
                computation="not_run",
            )
        values = (
            item.normal_force_n,
            item.tangential_force_n,
            item.friction_coefficient,
        )
    elif check == "joint":
        if not case.joint_demands:
            return result(
                "needs_measurement",
                "Supply stage-bound joint demands and matching scalar-mode allowables",
                computation="not_run",
            )
        if any(not j.scalar_mode_applicable for j in case.joint_demands):
            return result(
                "unsupported",
                "Joint interaction, peel, moment, fatigue and unsolved load paths are not inferred",
                computation="not_run",
            )
        values = tuple(
            q for j in case.joint_demands for q in (j.demand_n, j.allowable_n)
        )
    else:
        item = case.deformation
        if item is None:
            return result(
                "needs_measurement",
                "Supply a named beam boundary/load model, stiffness and allowable deflection",
                computation="not_run",
            )
        if not item.linear_elastic_small_deflection_applicable:
            return result(
                "unsupported",
                "Requires prismatic linear-elastic small-deflection Euler-Bernoulli beam applicability",
                computation="not_run",
            )
        values = (
            item.force_n,
            item.length_m,
            item.elastic_modulus_pa,
            item.second_moment_m4,
            item.allowable_deflection_m,
        )
    if any(q.kind == "unknown" for q in values):
        return result(
            "needs_measurement",
            "Required demand or material/capacity input is unknown",
            values,
            "not_run",
        )
    if any(q.kind != "scalar" for q in values):
        return result(
            "indeterminate",
            "Constitutive checks do not certify interval uncertainty by sampling",
            values,
            "not_run",
        )
    try:
        if check == "slide":
            normal, demand, coefficient = (q.value for q in values)
            if normal == 0:
                return result(
                    "unsupported",
                    "Zero compressive reaction cannot establish a sustained friction contact",
                    values,
                    "not_run",
                )
            capacity = coefficient * normal
            derived = _derived(capacity, "N")
            status = _compare(
                capacity, demand, policy.force_tolerance_n, policy.relative_tolerance
            )
            reason = f"{item.contact_id}: Coulomb capacity mu*N={capacity:.9g} N against supplied tangential demand={demand:.9g} N; no reaction distribution is solved"
        elif check == "joint":
            states = [
                _compare(
                    j.allowable_n.value,
                    j.demand_n.value,
                    policy.force_tolerance_n,
                    policy.relative_tolerance,
                )
                for j in case.joint_demands
            ]
            status = (
                "modeled_fail"
                if "modeled_fail" in states
                else "indeterminate"
                if "indeterminate" in states
                else "modeled_pass"
            )
            governing = min(
                case.joint_demands, key=lambda j: j.allowable_n.value - j.demand_n.value
            )
            reason = f"Checked {len(states)} supplied scalar joint modes: {states.count('modeled_fail')} fail, {states.count('indeterminate')} at tolerance boundary. Smallest force reserve: {governing.joint_id}, supplied demand={governing.demand_n.value:.9g} N, allowable={governing.allowable_n.value:.9g} N. Only supplied modes are covered; no load-path solution or other failure mode is inferred. Capacity basis is retained in the exact input."
            derived = None
        else:
            force, length, modulus, inertia, allowable = (q.value for q in values)
            divisor = 3 if item.support_model == "cantilever_end_load" else 48
            numerator = force * length**3
            denominator = divisor * modulus * inertia
            if (
                not math.isfinite(numerator)
                or not math.isfinite(denominator)
                or denominator <= 0
            ):
                raise FloatingPointError("Nonfinite beam intermediate")
            deflection = numerator / denominator
            derived = _derived(deflection, "m")
            # The declared small-deflection assumption cannot override an output
            # comparable to the span. This is a model-validity guard, not a safe load.
            if deflection >= length / 10:
                return result(
                    "unsupported",
                    "Computed deflection is at least 10% of span; the linear small-deflection model is outside this implementation's validity guard",
                    (*values, derived),
                    "not_run",
                )
            status = _compare(
                allowable,
                deflection,
                policy.length_tolerance_m,
                policy.relative_tolerance,
            )
            reason = f"{item.member_id}: {item.support_model}, P*L^3/({divisor}*E*I)={deflection:.9g} m against supplied allowable={allowable:.9g} m; excludes shear deformation, buckling, creep and material failure"
        return result(status, reason, values if derived is None else (*values, derived))
    except (ArithmeticError, ValueError):
        return result(
            "indeterminate",
            "Numerical constitutive computation failed",
            computation="numerical_failure",
        )
