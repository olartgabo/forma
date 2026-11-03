"""Pure, gravity-only rigid-assembly stability analysis; no physical pass."""

import hashlib
import json
import math

import numpy as np
import shapely
from shapely.geometry import MultiPoint, Polygon
from shapely.geometry.polygon import orient

from forma_domain.stability_contracts import (
    AnalysisPolicy,
    CheckResult,
    Point3,
    StabilityInput,
    StabilityOverlay,
    StabilityReport,
)

ENGINE_VERSION = "s1.0.0"


class _InvalidGeometry(ValueError):
    """A finite but invalid support geometry, distinct from numeric failure."""


def _normalized(value):
    if isinstance(value, dict):
        return {k: _normalized(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        values = [_normalized(v) for v in value]
        if values and isinstance(values[0], dict):
            for key in ("contact_id", "case_id", "body_id"):
                if all(key in item for item in values):
                    return sorted(values, key=lambda item: item[key])
        if all(isinstance(item, str) for item in values):
            return sorted(values)
        return values
    if isinstance(value, float) and value == 0:
        return 0.0
    return value


def _cache_hash(analysis, policy):
    data = dict(
        input=analysis.model_dump(mode="json"),
        policy=policy.model_dump(mode="json"),
        engine=ENGINE_VERSION,
        numpy=np.__version__,
        shapely=shapely.__version__,
        geos=shapely.geos_version_string,
    )
    encoded = json.dumps(
        _normalized(data), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _case(analysis, case, policy):
    snapshot = analysis.mechanical_snapshot
    if not (
        snapshot.rigid_assembly
        and snapshot.horizontal_support
        and snapshot.gravity_only
    ):
        return (
            "unsupported",
            "Requires rigid assembly, horizontal support and gravity-only loading",
            None,
        )
    bodies = sorted(
        (b for b in snapshot.bodies if b.body_id in case.body_ids),
        key=lambda b: b.body_id,
    )
    contacts = sorted(
        (c for c in snapshot.contacts if c.contact_id in case.contact_ids),
        key=lambda c: c.contact_id,
    )
    if any(b.state != "present" for b in bodies):
        return (
            "unsupported",
            "Case includes future bodies outside the current state",
            None,
        )
    if not contacts or any(not c.active for c in contacts):
        return (
            "needs_measurement",
            "Active supporting contacts must be established",
            None,
        )
    quantities = [case.gravity_m_s2]
    for body in bodies:
        quantities += [
            body.mass,
            body.center_of_mass.x,
            body.center_of_mass.y,
            body.center_of_mass.z,
        ]
    if any(q.kind == "unknown" for q in quantities):
        return (
            "needs_measurement",
            "Mass, world COM and gravity require known measurements or explicit modeled values",
            None,
        )
    if any(q.kind != "scalar" for q in quantities):
        return (
            "indeterminate",
            "S1 does not certify interval uncertainty by sampling",
            None,
        )
    points = [p for contact in contacts for p in contact.polygon_world]
    z = points[0].z
    if any(p.z != z for p in points):
        return "unsupported", "Contacts must share an exact horizontal plane", None
    for contact in contacts:
        xy = [(p.x, p.y) for p in contact.polygon_world]
        polygon = Polygon(xy)
        if not polygon.is_valid or polygon.area <= 0 or len(set(xy)) != len(xy):
            raise _InvalidGeometry("Invalid or degenerate contact polygon")
    hull = MultiPoint([(p.x, p.y) for p in points]).convex_hull
    if hull.geom_type != "Polygon" or not hull.is_valid or hull.area <= 0:
        raise _InvalidGeometry("Degenerate support footprint")
    hull = orient(hull, sign=1.0)
    vertices = list(hull.exterior.coords)[:-1]
    # Canonical starting vertex keeps overlays stable under contact ordering.
    start = min(range(len(vertices)), key=lambda i: vertices[i])
    vertices = vertices[start:] + vertices[:start]
    masses = np.array([b.mass.value for b in bodies], dtype=float)
    coordinates = np.array(
        [
            [
                b.center_of_mass.x.value,
                b.center_of_mass.y.value,
                b.center_of_mass.z.value,
            ]
            for b in bodies
        ]
    )
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        total = float(np.sum(masses))
        com = np.sum((masses / total)[:, None] * coordinates, axis=0)
        distances = []
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            distance = (dx * (com[1] - a[1]) - dy * (com[0] - a[0])) / math.hypot(
                dx, dy
            )
            distances.append(float(distance))
        edge = min(range(len(distances)), key=lambda i: distances[i])
        margin = distances[edge]
        moment = total * case.gravity_m_s2.value * margin
    if not all(math.isfinite(v) for v in (*com, total, margin, moment)):
        raise FloatingPointError("nonfinite modeled result")
    tolerance = max(
        policy.length_tolerance_m,
        policy.relative_tolerance
        * max(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(vertices, vertices[1:] + vertices[:1])
        ),
    )
    difference = margin - policy.required_margin_m
    status = (
        "modeled_pass"
        if difference > tolerance
        else "modeled_fail"
        if difference < -tolerance
        else "indeterminate"
    )
    overlay = StabilityOverlay(
        case_id=case.case_id,
        orientation=case.orientation,
        center_of_mass=Point3(x=float(com[0]), y=float(com[1]), z=float(com[2])),
        support_polygon=tuple(Point3(x=x, y=y, z=z) for x, y in vertices),
        critical_edge=tuple(
            Point3(x=x, y=y, z=z)
            for x, y in (vertices[edge], vertices[(edge + 1) % len(vertices)])
        ),
        signed_margin_m=margin,
        restoring_moment_n_m=moment,
    )
    reason = (
        "Signed COM clearance compared with the physical margin and numerical tolerance"
    )
    if status == "indeterminate":
        reason = "COM clearance overlaps the numerical boundary tolerance band"
    return status, reason, overlay


def evaluate_stability(
    analysis: StabilityInput, policy: AnalysisPolicy
) -> StabilityReport:
    """Evaluate each named world-space case; caller resolves authoritative identity.

    No BuildPlan/viewer pose inference, network, persistence or physical events.
    S1 exact scalars only; intervals remain unresolved.
    """
    results, overlays = [], []
    remaining_budget = policy.evaluation_budget
    cases = {case.case_id: case for case in analysis.cases}
    case_ids = set(cases) | set(policy.required_case_ids)
    if len(case_ids) > 16:
        raise ValueError("declared and required case union exceeds sixteen cases")
    for case_id in sorted(case_ids):
        case = cases.get(case_id)
        computation = "complete"
        if case is None:
            status, reason, overlay = (
                "indeterminate",
                "Required named load case is missing",
                None,
            )
            computation = "not_run"
        elif remaining_budget <= 0:
            status, reason, overlay = (
                "indeterminate",
                "Case evaluation budget exhausted",
                None,
            )
            computation = "budget_exhausted"
        else:
            remaining_budget -= 1
            try:
                status, reason, overlay = _case(analysis, case, policy)
            except _InvalidGeometry as error:
                status, reason, overlay = "indeterminate", str(error), None
                computation = "invalid_input"
            except (
                FloatingPointError,
                OverflowError,
                ValueError,
                shapely.errors.GEOSException,
            ):
                status, reason, overlay = (
                    "indeterminate",
                    "Numerical geometry computation failed",
                    None,
                )
                computation = "numerical_failure"
        if overlay is not None:
            overlays.append(overlay)
        for check in sorted(set(policy.required_check_types) | {"support", "tip"}):
            check_status, explanation, mode = status, reason, computation
            if check not in ("support", "tip"):
                check_status, explanation, mode = (
                    "unsupported",
                    "S1 does not model sliding, joints or deformation",
                    "not_run",
                )
            unresolved = (
                ()
                if check_status in ("modeled_pass", "modeled_fail")
                else (explanation,)
            )
            results.append(
                CheckResult(
                    case_id=case_id,
                    check_type=check,
                    status=check_status,
                    computation=mode,
                    explanation=explanation
                    + "; applicability: explicit rigid assembly, horizontal support, gravity only",
                    unresolved_predicates=unresolved,
                )
            )
    required = [
        r
        for r in results
        if r.case_id in policy.required_case_ids
        and r.check_type in policy.required_check_types
    ]
    status = "modeled_pass"
    for candidate in (
        "modeled_fail",
        "needs_measurement",
        "indeterminate",
        "unsupported",
    ):
        if any(r.status == candidate for r in results):
            status = candidate
            break
    unresolved = tuple(
        dict.fromkeys(p for r in results for p in r.unresolved_predicates)
    )
    snapshot = analysis.mechanical_snapshot
    assumptions = tuple(
        sorted(
            set(snapshot.assumption_ids)
            | {a for c in snapshot.contacts for a in c.assumption_ids}
        )
    )
    warnings = []
    for body in snapshot.bodies:
        for label, quantity in (
            ("mass", body.mass),
            ("COM x", body.center_of_mass.x),
            ("COM y", body.center_of_mass.y),
            ("COM z", body.center_of_mass.z),
        ):
            if quantity.kind == "scalar" and (
                not quantity.confirmed or quantity.provenance == "assumed"
            ):
                warnings.append(
                    f"{body.body_id} {label}: {quantity.provenance}, confirmed={quantity.confirmed}"
                )
    for case in analysis.cases:
        quantity = case.gravity_m_s2
        if quantity.kind == "scalar" and (
            not quantity.confirmed or quantity.provenance == "assumed"
        ):
            warnings.append(
                f"{case.case_id} gravity: {quantity.provenance}, confirmed={quantity.confirmed}"
            )
    return StabilityReport(
        identity=analysis.identity,
        report_version="s1",
        engine_version=ENGINE_VERSION,
        geometry_version=analysis.geometry_version,
        profile_version=analysis.profile_version,
        cache_hash=_cache_hash(analysis, policy),
        policy=policy,
        status=status,
        coverage="unsupported"
        if all(r.status == "unsupported" for r in required)
        else "complete",
        results=tuple(results),
        unresolved_predicates=unresolved,
        overlays=tuple(overlays),
        assumption_ids=assumptions,
        state_basis=snapshot.state_basis,
        input_warnings=tuple(warnings),
    )
