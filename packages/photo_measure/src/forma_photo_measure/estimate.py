"""Deterministic planar dimension estimate from one photo and one reference.

Thresholds below are capture rules chosen before any real-photo evaluation.
They flag observable problems; passing them does not prove accuracy.
"""

import hashlib
import json

import cv2
import numpy as np
from shapely.geometry import Polygon

from forma_domain.photo_measurement_contracts import (
    CARD_HEIGHT_MM,
    CARD_MARKER_IDS,
    CARD_WIDTH_MM,
    DIMENSION_DEFINITIONS,
    Diagnostic,
    DimensionEstimate,
    EstimateInput,
    PhotoEstimate,
    PixelPoint,
    Uncertainty,
)

from . import geometry as g
from .calibration import binding, undistort
from .card import marker_corners_mm
from .detect import detect_markers, edge_spread_px
from .outline import Outline, from_polygon, refine_box

SAMPLES = 200
# One-standard-deviation localisation assumptions, in image pixels.
REFERENCE_SIGMA_PX = {"detected": 0.3, "user": 1.5}
OUTLINE_SIGMA_PX = {"sam_box": 1.0, "manual_box": 1.0, "user_polygon": 2.0}
DISPLAY_STEPS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
RULES = {
    "reference_min_side_px": (50.0, 25.0),  # warning below, blocking below
    "edge_spread_px": (3.5, 7.0),  # warning above, blocking above
    "anisotropy": (3.0, 6.0),  # foreshortening ratio at the material
    "mm_per_px": (1.0, 2.5),  # coarsest resolution at the material
    "fit_rms_mm": (0.5, 1.5),
    "holdout_mm": (1.0, 3.0),
    "extrapolation": 6.0,  # material reach / reference diagonal
    "relative_spread": 0.10,  # sensitivity half-width / value
    "printed_scale": 0.15,  # check line differs from nominal by more than this
    "square_corner_deg": 3.0,
    "opposite_edge_mm": 2.0,
    "opposite_edge_ratio": 0.02,
    "rectangularity": 0.97,
    "edge_residual_px": 2.0,  # RMS scatter of a traced straight edge
}

REQUESTS = {
    "reference_unverified": "Measure printed line A on the card with a ruler (and line B if you can) and enter what you read. Printer scaling changes the card size.",
    "reference_not_found": "Take a new photo with the whole reference flat, unfolded and in focus beside the material.",
    "outline_clipped": "Part of the material is cut off at the photo edge. Step back so the whole piece and the reference are in view.",
    "outline_box_too_tight": "The box cuts off part of the material. Enlarge the box around the whole piece.",
    "outline_not_found": "The material edge could not be found. Draw its outline by placing its corners.",
}


def digest(data: EstimateInput) -> str:
    canonical = json.dumps(
        data.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _points(array) -> tuple[PixelPoint, ...]:
    return tuple(
        PixelPoint(x=float(x), y=float(y)) for x, y in np.asarray(array).reshape(-1, 2)
    )


class _Builder:
    def __init__(self, data: EstimateInput):
        self.data = data
        self.digest = digest(data)
        self.diagnostics: list[Diagnostic] = []
        self.assumptions: list[str] = [
            "The material lies flat on the same surface as the reference, as you stated; a photo cannot prove this.",
            "Thickness, strength, mass, friction, hidden damage and remaining tape length are not estimated from photos.",
        ]
        self.extra: dict = {}

    def note(self, code, severity, message, value=None):
        self.diagnostics.append(
            Diagnostic(
                code=code,
                severity=severity,
                message=message,
                value=None if value is None else float(value),
            )
        )

    def has(self, code):
        return any(d.code == code for d in self.diagnostics)

    def blocking(self):
        return next((d for d in self.diagnostics if d.severity == "blocking"), None)

    def result(self, outcome, request=None, **fields) -> PhotoEstimate:
        return PhotoEstimate(
            input_digest=self.digest,
            input=self.data,
            outcome=outcome,
            request=request,
            diagnostics=tuple(self.diagnostics[:32]),
            assumptions=tuple(self.assumptions[:12]),
            calibration_status=self.extra.get("calibration_status", "uncalibrated"),
            **{k: v for k, v in self.extra.items() if k != "calibration_status"},
            **fields,
        )


def _reference(builder: _Builder, gray: np.ndarray):
    """Image/plane correspondence groups, scale model and corner sigma, or a failed result."""

    ref = builder.data.reference
    tolerance = ref.size_tolerance_mm
    if ref.kind == "forma_card":
        if ref.printed_check_x_mm is None:
            builder.note(
                "reference_unverified",
                "blocking",
                "The printed card size has not been checked with a ruler.",
            )
            return builder.result(
                "reference_unverified", REQUESTS["reference_unverified"]
            )
        sx = ref.printed_check_x_mm / CARD_WIDTH_MM
        sy = (ref.printed_check_y_mm / CARD_HEIGHT_MM) if ref.printed_check_y_mm else sx
        if max(abs(sx - 1), abs(sy - 1)) > RULES["printed_scale"]:
            builder.note(
                "reference_unverified",
                "blocking",
                "The measured check lines differ from the card by more than 15 %; re-measure them.",
                max(sx, sy),
            )
            return builder.result(
                "reference_unverified", REQUESTS["reference_unverified"]
            )
        if not ref.printed_check_y_mm:
            builder.assumptions.append(
                "Printer scaling is assumed equal in both directions; line B was not measured."
            )
        if ref.corners_px:
            source = "user"
            corners = np.array(
                [(p.x, p.y) for p in ref.corners_px], np.float64
            ).reshape(4, 4, 2)
            ids = list(CARD_MARKER_IDS)
        else:
            source = "detected"
            markers = detect_markers(gray)
            ids = [i for i in CARD_MARKER_IDS if i in markers]
            if not ids:
                builder.note(
                    "reference_not_found", "blocking", "No FORMA card marker was found."
                )
                return builder.result(
                    "reference_not_found", REQUESTS["reference_not_found"]
                )
            corners = np.array([markers[i] for i in ids])
            if len(ids) < 4:
                builder.note(
                    "reference_partial",
                    "warning",
                    f"Only {len(ids)} of 4 card markers were found.",
                    len(ids),
                )

        def plane(scale_x, scale_y):
            return [marker_corners_mm(i, scale_x, scale_y) for i in ids]

        nominal = (sx, sy)

        def sample_plane(rng):
            ex = rng.uniform(-1, 1) * tolerance / CARD_WIDTH_MM
            ey = (
                rng.uniform(-1, 1) * tolerance / CARD_HEIGHT_MM
                if ref.printed_check_y_mm
                else ex
            )
            return plane(sx * (1 + ex), sy * (1 + ey))

        groups_mm = plane(*nominal)
        diagonal = float(np.hypot(CARD_WIDTH_MM * sx, CARD_HEIGHT_MM * sy))
    else:
        width, height = ref.width_mm, ref.height_mm
        if ref.kind == "aruco_marker" and not ref.corners_px:
            source = "detected"
            markers = detect_markers(gray)
            if ref.aruco_id not in markers:
                builder.note(
                    "reference_not_found",
                    "blocking",
                    f"Marker {ref.aruco_id} was not found.",
                )
                return builder.result(
                    "reference_not_found", REQUESTS["reference_not_found"]
                )
            corners = markers[ref.aruco_id][None]
        else:
            source = "user"
            corners = np.array([(p.x, p.y) for p in ref.corners_px], np.float64)[None]

        def rect(w, h):
            return [np.array(((0, 0), (w, 0), (w, h), (0, h)), np.float64)]

        def sample_plane(rng):
            w = width + rng.uniform(-1, 1) * tolerance
            h = (
                w
                if ref.kind == "aruco_marker"
                else height + rng.uniform(-1, 1) * tolerance
            )
            return rect(w, h)

        groups_mm = rect(width, height)
        diagonal = float(np.hypot(width, height))
    builder.assumptions.append(
        f"Reference size is within ±{tolerance:g} mm of the stated size."
    )
    sigma = REFERENCE_SIGMA_PX[source]
    builder.assumptions.append(
        f"Reference corners are located within {sigma:g} px (one standard deviation)."
    )
    return list(corners), groups_mm, sample_plane, sigma, diagonal, source


def _check_reference(builder: _Builder, gray, corners, source) -> None:
    for quad in corners:
        if not g.convex_quad(quad) or g.min_angle_deg(quad) < 20:
            builder.note(
                "degenerate_reference",
                "blocking",
                "The reference corners do not form a usable four-sided shape. Check their order and placement.",
            )
            return
    side = min(np.linalg.norm(q[(i + 1) % 4] - q[i]) for q in corners for i in range(4))
    warn, block = RULES["reference_min_side_px"]
    if side < block:
        builder.note(
            "reference_too_small",
            "blocking",
            "The reference is too small in the photo. Move closer.",
            side,
        )
    elif side < warn:
        builder.note(
            "reference_too_small",
            "warning",
            "The reference is small in the photo; corner errors weigh more.",
            side,
        )
    if builder.data.reference.kind != "rectangle":
        spreads = [
            s for s in (edge_spread_px(gray, q) for q in corners) if s is not None
        ]
        if spreads:
            spread = float(np.median(spreads))
            warn, block = RULES["edge_spread_px"]
            if spread > block:
                builder.note(
                    "reference_blurry",
                    "blocking",
                    "The reference is blurred. Hold the camera still and refocus.",
                    spread,
                )
            elif spread > warn:
                builder.note(
                    "reference_blurry",
                    "warning",
                    "The reference edges are soft; the photo may be slightly blurred.",
                    spread,
                )


class _Quad:
    """Four edge lines in (undistorted) image pixels."""

    def __init__(self, lines, residual_px=0.0):
        self.lines = lines  # list of (point, unit direction)
        # Worst per-edge RMS distance of traced points from their fitted line.
        self.residual_px = residual_px

    def corners(self, offsets=(0, 0, 0, 0)):
        shifted = []
        for (p, d), offset in zip(self.lines, offsets):
            normal = np.array([-d[1], d[0]])
            shifted.append((p + normal * offset, d))
        return np.array(
            [g.line_intersection(*shifted[i - 1], *shifted[i]) for i in range(4)]
        )


def _find_quad(outer: np.ndarray, holes) -> _Quad | None:
    if holes:
        return None
    contour = outer.astype(np.float32).reshape(-1, 1, 2)
    approx = cv2.approxPolyDP(
        contour, 0.02 * cv2.arcLength(contour, True), True
    ).reshape(-1, 2)
    if len(approx) != 4 or not g.convex_quad(approx.astype(np.float64)):
        return None
    approx = approx.astype(np.float64)
    if len(outer) == 4:
        return _Quad(
            [
                (
                    approx[i],
                    (approx[(i + 1) % 4] - approx[i])
                    / np.linalg.norm(approx[(i + 1) % 4] - approx[i]),
                )
                for i in range(4)
            ]
        )
    lines, residuals = [], []
    for i in range(4):
        a, b = approx[i], approx[(i + 1) % 4]
        length = np.linalg.norm(b - a)
        direction = (b - a) / length
        t = (outer - a) @ direction
        distance = np.abs((outer - a) @ np.array([-direction[1], direction[0]]))
        chosen = outer[
            (t > 0.08 * length)
            & (t < 0.92 * length)
            & (distance < max(3.0, 0.03 * length))
        ]
        if len(chosen) < 5:
            lines.append((a, direction))
            continue
        vx, vy, x0, y0 = cv2.fitLine(
            chosen.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01
        ).reshape(-1)
        fitted = np.array([vx, vy], np.float64)
        if np.dot(fitted, direction) < 0:
            fitted = -fitted
        origin = np.array([x0, y0], np.float64)
        normal = np.array([-fitted[1], fitted[0]])
        residuals.append(float(np.sqrt(np.mean(((chosen - origin) @ normal) ** 2))))
        lines.append((origin, fitted))
    return _Quad(lines, max(residuals, default=0.0))


def _quad_dims(h, corners_px):
    mm = g.apply(h, corners_px)
    sides = [np.linalg.norm(mm[(i + 1) % 4] - mm[i]) for i in range(4)]
    a, b = (sides[0] + sides[2]) / 2, (sides[1] + sides[3]) / 2
    return (
        {
            "edge_length_mm": max(a, b),
            "edge_width_mm": min(a, b),
            "outline_area_mm2": Polygon(mm).area,
        },
        sides,
        mm,
    )


def _irregular_dims(h, outer, holes):
    polygon = Polygon(g.apply(h, outer), [g.apply(h, x) for x in holes])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    rect = np.array(polygon.minimum_rotated_rectangle.exterior.coords[:4])
    sides = [np.linalg.norm(rect[(i + 1) % 4] - rect[i]) for i in range(2)]
    dims = {
        "enclosing_length_mm": max(sides),
        "enclosing_width_mm": min(sides),
        "outline_area_mm2": polygon.area,
    }
    if holes:
        dims["hole_area_mm2"] = sum(Polygon(g.apply(h, x)).area for x in holes)
    return dims


def _display(value, low, high, check_mm, unit):
    spread = max(value - low, high - value)
    if unit == "mm":
        need = max(spread, check_mm or 0.0)
        step = next((s for s in DISPLAY_STEPS if s >= need), None)
        return step, need
    magnitude = max(spread, 1.0)
    decade = float(10 ** np.floor(np.log10(magnitude)))
    step = next(s * decade for s in (1, 2, 5, 10) if s * decade >= magnitude)
    return step, spread


def estimate(image: np.ndarray, data: EstimateInput) -> PhotoEstimate:
    """Estimate planar dimensions. Never confirms a value or reads thickness."""

    if image.shape[:2] != (data.image_height_px, data.image_width_px):
        raise ValueError("image size does not match the stored photo")
    builder = _Builder(data)
    builder.note(
        "thickness_not_measurable",
        "info",
        "Thickness cannot be measured from a photo taken from above.",
    )
    status = binding(data.calibration, data.image_width_px, data.image_height_px)
    builder.extra["calibration_status"] = status
    if status == "mismatch":
        builder.note(
            "calibration_mismatch",
            "warning",
            "The saved lens calibration is for a different image size; it was not applied.",
        )
    if status == "applied":
        builder.note(
            "calibration_applied",
            "info",
            f"Lens calibration '{data.calibration.device_label}' applied.",
        )
        builder.assumptions.append(
            "The photo came from the calibrated device, uncropped and without digital zoom."
        )
    else:
        builder.note(
            "lens_uncorrected",
            "warning",
            "Lens distortion is not corrected. Errors grow toward the photo edges.",
        )
        builder.assumptions.append(
            "Lens distortion is not corrected; keep material and reference near the photo centre."
        )

    capture = data.capture
    if data.stock_kind in ("tape", "cord"):
        builder.note(
            "unsupported_shape",
            "blocking",
            "Rolls and cords are not flat; their width and remaining length cannot be measured from a photo.",
        )
        what = "the tape width" if data.stock_kind == "tape" else "the cord length"
        return builder.result(
            "unsupported_shape",
            f"Measure {what} with a ruler. Remaining length cannot be seen in a photo.",
        )
    if capture.shape != "flat":
        builder.note(
            "unsupported_shape",
            "blocking",
            f"A {capture.shape} item has no single planar size in a photo.",
        )
        return builder.result(
            "unsupported_shape",
            "Lay the piece flat beside the reference and take a new photo, or measure it with a ruler.",
        )
    if not capture.same_surface_as_reference:
        builder.note(
            "not_on_reference_plane",
            "blocking",
            "The material is not on the same surface as the reference.",
        )
        return builder.result(
            "unsupported_shape",
            "Place the material flat on the same surface as the reference and take a new photo.",
        )

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found = _reference(builder, gray)
    if isinstance(found, PhotoEstimate):
        return found
    corners, groups_mm, sample_plane, ref_sigma, diagonal, source = found
    for quad in corners:
        if (
            np.any(quad < -0.5)
            or np.any(quad[:, 0] > data.image_width_px - 0.5)
            or np.any(quad[:, 1] > data.image_height_px - 0.5)
        ):
            raise ValueError("reference corners lie outside the photo")
    builder.extra["reference_corners_px"] = _points(np.vstack(corners))
    builder.extra["reference_corners_mm"] = _points(np.vstack(groups_mm))
    _check_reference(builder, gray, corners, source)
    if (block := builder.blocking()) is not None:
        return builder.result("needs_better_photo", block.message)

    fix = (
        (lambda p: undistort(p, data.calibration))
        if status == "applied"
        else (lambda p: np.asarray(p, np.float64))
    )
    groups_px = [fix(q) for q in corners]
    all_px, all_mm = np.vstack(groups_px), np.vstack(groups_mm)
    try:
        h = g.fit_homography(all_px, all_mm)
    except g.Degenerate:
        builder.note(
            "degenerate_reference",
            "blocking",
            "The reference corners cannot define the surface.",
        )
        return builder.result(
            "needs_better_photo",
            "Retake the photo with the whole reference visible and not edge-on.",
        )
    fit_rms = g.rms_residual_mm(h, all_px, all_mm) if len(all_px) > 4 else None
    if fit_rms is not None:
        warn, block = RULES["fit_rms_mm"]
        if fit_rms > block:
            builder.note(
                "fit_residual_high",
                "blocking",
                "The reference points do not fit one flat surface. The card may be bent or the lens distortion strong.",
                fit_rms,
            )
        elif fit_rms > warn:
            builder.note(
                "fit_residual_high",
                "warning",
                "The reference points fit a flat surface only approximately.",
                fit_rms,
            )
    holdout = None
    if len(groups_px) >= 2:
        holdout = max(g.holdout_errors_mm(list(zip(groups_px, groups_mm))))
        warn, block = RULES["holdout_mm"]
        if holdout > block:
            builder.note(
                "holdout_error_high",
                "blocking",
                "Card markers disagree about the surface; check that the card is flat.",
                holdout,
            )
        elif holdout > warn:
            builder.note(
                "holdout_error_high",
                "warning",
                "Card markers agree only approximately.",
                holdout,
            )
    else:
        builder.note(
            "no_independent_check",
            "warning",
            "Only four reference corners: the fitted transform reproduces them exactly, so this photo cannot show how accurate it is.",
        )

    outline_in = data.outline
    sigma = OUTLINE_SIGMA_PX[outline_in.source]
    if outline_in.source == "user_polygon":
        outline: Outline = from_polygon(
            [(p.x, p.y) for p in outline_in.polygon_px],
            [[(p.x, p.y) for p in hole] for hole in outline_in.holes_px],
            sigma,
        )
    else:
        outline = refine_box(
            image, (outline_in.x1, outline_in.y1, outline_in.x2, outline_in.y2), sigma
        )
    if outline.problem:
        builder.note(outline.problem, "blocking", REQUESTS[outline.problem])
        return builder.result("needs_better_photo", REQUESTS[outline.problem])
    builder.extra["outline_px"] = _points(outline.outer)
    builder.extra["holes_px"] = tuple(_points(x) for x in outline.holes)
    builder.assumptions.append(
        f"The material outline is located within {outline.sigma_px:.2g} px (one standard deviation)."
    )
    outer, holes = fix(outline.outer), tuple(fix(x) for x in outline.holes)
    if not g.same_side(h, all_px, outer):
        builder.note(
            "outline_crosses_horizon",
            "blocking",
            "The outline reaches beyond the surface the reference defines.",
        )
        return builder.result(
            "needs_better_photo", "Take the photo from more directly above."
        )
    big, small = g.local_scale(h, outer.mean(axis=0))
    anisotropy = big / small
    warn, block = RULES["anisotropy"]
    if anisotropy > block:
        builder.note(
            "steep_angle",
            "blocking",
            "The photo is taken at a steep angle. Hold the camera more directly above.",
            anisotropy,
        )
    elif anisotropy > warn:
        builder.note(
            "steep_angle",
            "warning",
            "The photo is taken at an angle; small bends weigh more.",
            anisotropy,
        )
    warn, block = RULES["mm_per_px"]
    if big > block:
        builder.note(
            "low_resolution_at_material",
            "blocking",
            "The material is too small in the photo. Move closer.",
            big,
        )
    elif big > warn:
        builder.note(
            "low_resolution_at_material",
            "warning",
            "Each pixel covers more than 1 mm at the material.",
            big,
        )
    outline_mm = g.apply(h, outer)
    centre_mm = all_mm.mean(axis=0)
    reach = float(np.max(np.linalg.norm(outline_mm - centre_mm, axis=1)))
    if reach / diagonal > RULES["extrapolation"]:
        builder.note(
            "far_from_reference",
            "warning",
            "The material extends far beyond the reference; errors grow with distance.",
            reach / diagonal,
        )
    if (block := builder.blocking()) is not None:
        return builder.result("needs_better_photo", block.message)

    dense = fix(outline.dense) if outline.dense is not None else outer
    quad = _find_quad(dense, holes)
    if holes:
        builder.note(
            "holes_present",
            "info",
            "The outline has holes; only enclosing size and area are given.",
            len(holes),
        )
    rectangular = False
    outline_sigma = outline.sigma_px
    if quad is not None and quad.residual_px > RULES["edge_residual_px"]:
        builder.note(
            "irregular_outline",
            "info",
            "The traced edges are uneven, so the outline may include background or miss material. Adjust the outline or draw it.",
            quad.residual_px,
        )
        quad = None
    elif quad is not None:
        # The measured edge scatter is evidence of localisation error.
        outline_sigma = max(outline_sigma, quad.residual_px)
    if quad is not None:
        try:
            nominal, sides, mm = _quad_dims(h, quad.corners())
            angles = []
            for i in range(4):
                u, v = mm[i - 1] - mm[i], mm[(i + 1) % 4] - mm[i]
                angles.append(
                    np.degrees(
                        np.arccos(
                            np.clip(
                                np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v),
                                -1,
                                1,
                            )
                        )
                    )
                )
            area_ratio = Polygon(g.apply(h, outer)).area / nominal["outline_area_mm2"]
            differ = max(abs(sides[0] - sides[2]), abs(sides[1] - sides[3]))
            limit = max(
                RULES["opposite_edge_mm"], RULES["opposite_edge_ratio"] * max(sides)
            )
            if differ > limit:
                builder.note(
                    "opposite_edges_differ",
                    "warning",
                    "Opposite edges differ in length; the piece may not be rectangular or not flat.",
                    differ,
                )
            elif max(abs(a - 90) for a in angles) > RULES["square_corner_deg"]:
                builder.note(
                    "irregular_outline",
                    "info",
                    "The corners are not square; only enclosing size is given.",
                )
            elif area_ratio < RULES["rectangularity"]:
                builder.note(
                    "irregular_outline",
                    "info",
                    "The outline is not a clean rectangle; only enclosing size is given.",
                )
            else:
                rectangular = True
        except g.Degenerate:
            rectangular = False
    if not rectangular:
        if quad is None and not holes and not builder.has("irregular_outline"):
            builder.note(
                "irregular_outline",
                "info",
                "The outline is not four-sided; only enclosing size is given.",
            )
        nominal = _irregular_dims(h, outer, holes)

    rng = np.random.default_rng(int(builder.digest[:16], 16))
    samples = {name: [] for name in nominal}
    for _ in range(SAMPLES):
        px = all_px + rng.normal(0, ref_sigma, all_px.shape)
        try:
            hs = g.fit_homography(px, np.vstack(sample_plane(rng)))
            if rectangular:
                values, _, _ = _quad_dims(
                    hs, quad.corners(rng.normal(0, outline_sigma, 4))
                )
            else:
                grown = Polygon(outer, holes).buffer(
                    rng.normal(0, outline_sigma), join_style="mitre"
                )
                if grown.geom_type != "Polygon" or grown.is_empty:
                    continue
                values = _irregular_dims(
                    hs,
                    np.array(grown.exterior.coords[:-1]),
                    tuple(np.array(r.coords[:-1]) for r in grown.interiors),
                )
        except (g.Degenerate, ValueError):
            continue
        for name in samples:
            if name in values:
                samples[name].append(values[name])
    dimensions = []
    for name, value in nominal.items():
        values = np.array(samples[name]) if samples[name] else np.array([value])
        low, high = (float(np.percentile(values, 5)), float(np.percentile(values, 95)))
        unit = "mm2" if name.endswith("mm2") else "mm"
        step, need = _display(value, low, high, holdout, unit)
        if unit == "mm" and (holdout is None or status != "applied"):
            # Uncorrected lens or no independent check: unmodelled error the
            # sensitivity cannot show, so never display finer than this floor.
            floor = max(2.0, 0.01 * value)
            if need < floor:
                need = floor
                step = next((s for s in DISPLAY_STEPS if s >= need), None)
        if unit == "mm" and (step is None or need > RULES["relative_spread"] * value):
            message = f"The photo leaves about ±{need:.0f} mm of doubt on this piece."
            builder.note("low_resolution_at_material", "blocking", message, need)
            return builder.result(
                "needs_better_photo",
                message
                + " Move closer and hold the camera more directly above, or measure it with a ruler.",
            )
        field = None
        if rectangular and name == "edge_length_mm":
            field = "width_mm"
        elif rectangular and name == "edge_width_mm":
            field = "height_mm"
        dimensions.append(
            DimensionEstimate(
                name=name,
                definition=DIMENSION_DEFINITIONS[name],
                unit=unit,
                value=float(value),
                display_value=float(round(value / step) * step),
                display_step=float(step),
                sensitivity_low=low,
                sensitivity_high=high,
                stock_field=field,
            )
        )
    uncertainty = Uncertainty(
        samples=SAMPLES,
        reference_corner_sigma_px=ref_sigma,
        outline_sigma_px=outline_sigma,
        outline_edge_residual_px=quad.residual_px if rectangular else None,
        reference_size_tolerance_mm=data.reference.size_tolerance_mm,
        fit_rms_mm=fit_rms,
        holdout_max_error_mm=holdout,
        holdout_checks=len(groups_px) if holdout is not None else 0,
    )
    if rectangular:
        return builder.result(
            "estimate", dimensions=tuple(dimensions), uncertainty=uncertainty
        )
    return builder.result(
        "enclosing_only",
        "This piece is not a plain flat rectangle. Measure the rectangle you plan to cut from it with a ruler.",
        dimensions=tuple(dimensions),
        uncertainty=uncertainty,
    )
