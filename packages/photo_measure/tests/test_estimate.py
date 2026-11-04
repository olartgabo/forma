"""Synthetic geometry checks. These prove the math, not real-photo accuracy."""

import cv2
import numpy as np
import pytest
from forma_photo_measure import calibrate_from_card_views, card_svg, digest, estimate
from forma_photo_measure.card import DICTIONARY, MARKER_ORIGINS, marker_modules
from pydantic import ValidationError
from scenes import (
    CARD_AT,
    MATERIAL,
    PX_PER_MM,
    box_around,
    camera,
    card_reference,
    make_input,
    points,
    project,
    rect_mm,
    render,
    texture,
)

from forma_domain.models import Measurement
from forma_domain.photo_measurement_contracts import (
    CameraCalibration,
    OutlineInput,
    PhotoEstimate,
    ReferenceInput,
)

SHEET = rect_mm(200, 60, 280, 190)


def scene(outer=SHEET, holes=(), tilt=20.0, yaw=8.0, **kw):
    tex = texture(
        [(outer, holes, MATERIAL)],
        **{k: v for k, v in kw.items() if k in ("card", "single_marker", "card_scale")},
    )
    k, h = camera(
        tilt_deg=tilt,
        yaw_deg=yaw,
        **{k: v for k, v in kw.items() if k in ("distance", "size", "f", "shift")},
    )
    size = kw.get("size", (1600, 1200))
    image = render(tex, h, size=size, k=k, distortion=kw.get("distortion"))
    return image, h, k


def dims(result: PhotoEstimate):
    return {d.name: d for d in result.dimensions}


def assert_covers(d, truth, slack):
    assert abs(d.value - truth) <= slack, (d.name, d.value, truth)


@pytest.mark.parametrize("tilt,yaw", [(0, 0), (25, 15), (40, -30)])
def test_rectangular_sheet_under_perspective(tilt, yaw):
    image, h, _ = scene(tilt=tilt, yaw=yaw)
    result = estimate(image, make_input(image, box_around(h, SHEET)))
    assert result.outcome == "estimate"
    d = dims(result)
    assert_covers(d["edge_length_mm"], 280, 3)
    assert_covers(d["edge_width_mm"], 190, 3)
    assert d["edge_length_mm"].stock_field == "width_mm"
    assert d["edge_width_mm"].stock_field == "height_mm"
    for item in d.values():
        assert item.sensitivity_low <= item.value <= item.sensitivity_high
        # No decimal finer than the spread supports.
        assert (
            item.display_step
            >= (item.sensitivity_high - item.sensitivity_low) / 2 - 1e-9
        )
    assert result.uncertainty.holdout_checks == 4
    assert result.uncertainty.fit_rms_mm is not None
    assert result.measurement_status == "photo_estimate_unconfirmed"
    assert "not a calibrated confidence interval" in result.uncertainty.statement


def test_rotated_and_resized_photo_gives_same_physical_size():
    image, h, _ = scene()
    base = dims(estimate(image, make_input(image, box_around(h, SHEET))))
    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    rotated = cv2.resize(rotated, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
    # Map the box through the same rotation and scaling.
    corners = project(h, SHEET)
    rot = np.column_stack([image.shape[0] - 1 - corners[:, 1], corners[:, 0]]) * 0.75
    x1, y1 = np.floor(rot.min(axis=0) - 10).astype(int)
    x2, y2 = np.ceil(rot.max(axis=0) + 10).astype(int)
    outline = OutlineInput(
        source="manual_box", x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2)
    )
    after = dims(estimate(rotated, make_input(rotated, outline)))
    for name in ("edge_length_mm", "edge_width_mm"):
        assert abs(after[name].value - base[name].value) < 2.5
        assert_covers(after[name], 280 if "length" in name else 190, 3.5)


def test_slightly_tight_sam_box_still_finds_the_whole_sheet():
    image, h, _ = scene()
    p = project(h, SHEET)
    tight = OutlineInput(
        source="sam_box",
        x1=int(p[:, 0].min()) + 15,
        y1=int(p[:, 1].min()) + 15,
        x2=int(p[:, 0].max()) - 15,
        y2=int(p[:, 1].max()) - 15,
    )
    result = estimate(image, make_input(image, tight))
    assert result.outcome == "estimate"
    assert_covers(dims(result)["edge_length_mm"], 280, 3)


def test_input_size_must_match_stored_photo():
    image, h, _ = scene()
    data = make_input(image, box_around(h, SHEET))
    with pytest.raises(ValueError):
        estimate(image[:-1], data)


def test_reference_must_be_verified_and_size_errors_propagate():
    image, h, _ = scene()
    outline = box_around(h, SHEET)
    unverified = ReferenceInput(kind="forma_card", size_tolerance_mm=0.5)
    result = estimate(image, make_input(image, outline, reference=unverified))
    assert result.outcome == "reference_unverified" and not result.dimensions
    assert "ruler" in result.request
    implausible = card_reference(check_x=120, check_y=80)
    assert (
        estimate(image, make_input(image, outline, reference=implausible)).outcome
        == "reference_unverified"
    )
    # A wrongly entered check length scales every estimate by the same factor:
    # a reference mistake is not detectable from the photo, so it must be checked.
    wrong = dims(
        estimate(
            image,
            make_input(
                image, outline, reference=card_reference(check_x=145, check_y=96.67)
            ),
        )
    )
    assert_covers(wrong["edge_length_mm"], 280 * 145 / 150, 3)


def test_printed_scaling_is_corrected_by_the_measured_check_lines():
    # The card printed at 97 % ("fit to page"); the user measures 145.5 mm.
    image, h, _ = scene(card_scale=0.97)
    result = estimate(
        image,
        make_input(
            image,
            box_around(h, SHEET),
            reference=card_reference(check_x=145.5, check_y=97.0),
        ),
    )
    assert_covers(dims(result)["edge_length_mm"], 280, 3)


def test_wider_reference_tolerance_widens_the_sensitivity_range():
    image, h, _ = scene()
    outline = box_around(h, SHEET)
    tight = dims(
        estimate(
            image, make_input(image, outline, reference=card_reference(tolerance=0.2))
        )
    )
    loose = dims(
        estimate(
            image, make_input(image, outline, reference=card_reference(tolerance=3.0))
        )
    )
    spread = lambda d: d.sensitivity_high - d.sensitivity_low  # noqa: E731
    assert spread(loose["edge_length_mm"]) > spread(tight["edge_length_mm"]) * 1.5


def test_insufficient_reference_resolution_is_not_an_estimate():
    image, h, _ = scene()
    small = cv2.resize(image, None, fx=0.15, fy=0.15, interpolation=cv2.INTER_AREA)
    box = box_around(h, SHEET)
    outline = OutlineInput(
        source="manual_box",
        x1=int(box.x1 * 0.15),
        y1=int(box.y1 * 0.15),
        x2=int(box.x2 * 0.15),
        y2=int(box.y2 * 0.15),
    )
    result = estimate(small, make_input(small, outline))
    assert result.outcome in ("reference_not_found", "needs_better_photo")
    assert not result.dimensions and result.request


def test_blur_is_reported_from_the_reference_edges():
    image, h, _ = scene()
    blurred = cv2.GaussianBlur(image, (0, 0), 6)
    result = estimate(blurred, make_input(blurred, box_around(h, SHEET)))
    codes = {d.code: d.severity for d in result.diagnostics}
    assert result.outcome == "reference_not_found" or codes.get("reference_blurry") in (
        "warning",
        "blocking",
    )


def test_steep_angle_is_flagged():
    image, h, _ = scene(tilt=75, distance=500)
    result = estimate(image, make_input(image, box_around(h, SHEET)))
    codes = {d.code: d.severity for d in result.diagnostics}
    assert result.outcome != "estimate" or codes.get("steep_angle") == "warning"
    if result.outcome == "estimate":
        assert_covers(dims(result)["edge_length_mm"], 280, 4)


def test_irregular_outline_gives_enclosing_dimensions_only():
    l_shape = [(200, 60), (480, 60), (480, 140), (300, 140), (300, 250), (200, 250)]
    image, h, _ = scene(outer=l_shape)
    result = estimate(image, make_input(image, box_around(h, l_shape)))
    assert result.outcome == "enclosing_only"
    d = dims(result)
    assert set(d) >= {"enclosing_length_mm", "enclosing_width_mm", "outline_area_mm2"}
    assert all(x.stock_field is None for x in d.values())
    assert_covers(d["enclosing_length_mm"], 280, 3.5)
    true_area = 280 * 80 + 100 * 110
    assert abs(d["outline_area_mm2"].value - true_area) / true_area < 0.03
    assert "ruler" in result.request


def test_holes_are_preserved_and_never_counted_as_material():
    hole = rect_mm(300, 110, 60, 50)
    image, h, _ = scene(holes=[hole])
    result = estimate(image, make_input(image, box_around(h, SHEET)))
    assert result.outcome == "enclosing_only"
    d = dims(result)
    assert len(result.holes_px) == 1
    assert abs(d["hole_area_mm2"].value - 3000) / 3000 < 0.1
    assert abs(d["outline_area_mm2"].value - (280 * 190 - 3000)) / (280 * 190) < 0.03


def test_occluded_corner_is_not_reported_as_a_rectangle():
    tex = texture(
        [(SHEET, [], MATERIAL), (rect_mm(420, 190, 90, 90), [], (60, 160, 60))]
    )
    k, h = camera(tilt_deg=15)
    image = render(tex, h)
    result = estimate(image, make_input(image, box_around(h, SHEET)))
    assert result.outcome != "estimate"


@pytest.mark.parametrize("shape", ["curved", "folded", "stacked", "raised", "roll"])
def test_nonplanar_declarations_are_unsupported(shape):
    image, h, _ = scene()
    result = estimate(image, make_input(image, box_around(h, SHEET), shape=shape))
    assert result.outcome == "unsupported_shape" and not result.dimensions


def test_tape_and_other_planes_are_unsupported():
    image, h, _ = scene()
    tape = estimate(image, make_input(image, box_around(h, SHEET), kind="tape"))
    assert tape.outcome == "unsupported_shape" and "Remaining length" in tape.request
    raised = estimate(
        image, make_input(image, box_around(h, SHEET), same_surface=False)
    )
    assert raised.outcome == "unsupported_shape"


def test_clipped_material_and_tight_box_ask_for_a_fix():
    beyond = rect_mm(250, 60, 268, 190)
    image, h, _ = scene(outer=beyond, tilt=0, yaw=0, distance=480, shift=(-70, 0))
    corners = project(h, beyond)
    outline = OutlineInput(
        source="sam_box",
        x1=int(corners[:, 0].min()) - 5,
        y1=int(corners[:, 1].min()) - 5,
        x2=image.shape[1] - 1,
        y2=int(corners[:, 1].max()) + 5,
    )
    clipped = estimate(image, make_input(image, outline))
    assert (
        clipped.outcome == "needs_better_photo"
        and "cut off at the photo edge" in clipped.request
    )

    image, h, _ = scene()
    p = project(h, SHEET)
    tight = OutlineInput(
        source="sam_box",
        x1=int(p[:, 0].min()) + 150,
        y1=int(p[:, 1].min()) + 10,
        x2=int(p[:, 0].max()) - 150,
        y2=int(p[:, 1].max()) - 10,
    )
    result = estimate(image, make_input(image, tight))
    assert (
        result.outcome == "needs_better_photo" and "Enlarge the box" in result.request
    )


def test_small_hand_marked_reference_far_away_is_refused():
    image, h, _ = scene(card=False, single_marker=(7, (0, 0), 50.0))
    marker_px = project(h, rect_mm(CARD_AT[0], CARD_AT[1], 50, 50))
    rectangle = ReferenceInput(
        kind="rectangle",
        width_mm=50,
        height_mm=50,
        size_source="ruler",
        size_tolerance_mm=0.5,
        corners_px=points(marker_px),
    )
    polygon = OutlineInput(source="user_polygon", polygon_px=points(project(h, SHEET)))
    result = estimate(image, make_input(image, polygon, reference=rectangle))
    assert result.outcome == "needs_better_photo" and not result.dimensions
    assert "doubt" in result.request


def test_user_polygon_and_rectangle_reference_have_no_independent_check():
    image, h, _ = scene()
    card_px = project(h, rect_mm(CARD_AT[0], CARD_AT[1], 150, 100))
    rectangle = ReferenceInput(
        kind="rectangle",
        width_mm=150,
        height_mm=100,
        size_source="ruler",
        size_tolerance_mm=0.5,
        corners_px=points(card_px),
    )
    polygon = OutlineInput(source="user_polygon", polygon_px=points(project(h, SHEET)))
    result = estimate(image, make_input(image, polygon, reference=rectangle))
    assert result.outcome == "estimate"
    assert "no_independent_check" in {d.code for d in result.diagnostics}
    assert (
        result.uncertainty.holdout_checks == 0 and result.uncertainty.fit_rms_mm is None
    )
    assert_covers(dims(result)["edge_length_mm"], 280, 5)

    image, h, _ = scene(card=False, single_marker=(7, (0, 0), 80.0))
    marker = ReferenceInput(
        kind="aruco_marker",
        aruco_id=7,
        width_mm=80,
        height_mm=80,
        size_source="ruler",
        size_tolerance_mm=0.3,
    )
    detected = estimate(
        image, make_input(image, box_around(h, SHEET), reference=marker)
    )
    assert detected.outcome == "estimate"
    assert_covers(dims(detected)["edge_length_mm"], 280, 5)


def test_rectangle_reference_needs_a_proper_quad():
    image, h, _ = scene()
    flat = ReferenceInput(
        kind="rectangle",
        width_mm=85.6,
        height_mm=53.98,
        size_source="published_standard",
        size_tolerance_mm=0.2,
        corners_px=points([(10, 10), (200, 10), (400, 11), (600, 12)]),
    )
    result = estimate(image, make_input(image, box_around(h, SHEET), reference=flat))
    assert result.outcome == "needs_better_photo"
    assert "degenerate_reference" in {d.code for d in result.diagnostics}


def test_lens_distortion_and_calibration_binding():
    distortion = (-0.25, 0.08, 0.0, 0.0, 0.0)
    image, h, k = scene(tilt=10, distortion=distortion, shift=(60, 40))
    outline = box_around(h, SHEET, margin_px=30)
    raw = estimate(image, make_input(image, outline))
    calibration = CameraCalibration(
        calibration_id="cal-1",
        device_label="synthetic camera",
        image_width_px=1600,
        image_height_px=1200,
        camera_matrix=tuple(tuple(float(v) for v in row) for row in k),
        distortion=distortion,
        rms_reprojection_px=0.2,
        view_count=6,
    )
    corrected = estimate(image, make_input(image, outline, calibration=calibration))
    assert corrected.calibration_status == "applied"
    assert corrected.outcome == "estimate"
    assert_covers(dims(corrected)["edge_length_mm"], 280, 3)
    # Uncorrected, the bent edges are either refused as a rectangle or worse.
    if raw.outcome == "estimate":
        corrected_error = abs(dims(corrected)["edge_length_mm"].value - 280)
        assert corrected_error < abs(dims(raw)["edge_length_mm"].value - 280)
    else:
        assert raw.outcome in ("enclosing_only", "needs_better_photo")
    # The same calibration on a resized photo is a mismatch and is not applied.
    smaller = cv2.resize(image, (1200, 900), interpolation=cv2.INTER_AREA)
    box = OutlineInput(
        source="manual_box",
        x1=int(outline.x1 * 0.75),
        y1=int(outline.y1 * 0.75),
        x2=int(outline.x2 * 0.75),
        y2=int(outline.y2 * 0.75),
    )
    mismatch = estimate(smaller, make_input(smaller, box, calibration=calibration))
    assert mismatch.calibration_status == "mismatch"
    assert "calibration_mismatch" in {d.code for d in mismatch.diagnostics}


def test_calibration_from_card_views_recovers_the_lens():
    distortion = (-0.2, 0.05, 0.0, 0.0, 0.0)
    views = []
    for tilt, yaw, shift in [
        (0, 0, (0, 0)),
        (25, 10, (40, 0)),
        (-25, -15, (-40, 20)),
        (20, 60, (0, -30)),
        (30, -40, (30, 30)),
        (-15, 120, (-30, -20)),
    ]:
        tex = texture([])
        k, h = camera(
            tilt_deg=tilt,
            yaw_deg=yaw,
            distance=330,
            shift=(shift[0] - 165, shift[1] - 120),
        )
        views.append(render(tex, h, k=k, distortion=distortion))
    result = calibrate_from_card_views(views, "cal-2", "synthetic")
    assert result.rms_reprojection_px < 1.0
    assert abs(result.camera_matrix[0][0] - k[0, 0]) / k[0, 0] < 0.05
    assert result.distortion[0] < -0.1


def test_estimates_are_deterministic_and_bound_to_their_inputs():
    image, h, _ = scene()
    data = make_input(image, box_around(h, SHEET))
    assert estimate(image, data) == estimate(image, data)
    changed = data.model_copy(update={"reference": card_reference(check_x=149.0)})
    assert digest(changed) != digest(data)
    moved = data.model_copy(update={"stock_id": "sheet-b"})
    assert digest(moved) != digest(data)


def test_photo_estimates_can_never_be_confirmed_measurements():
    Measurement(value=280, unit="mm", source="photo_estimate", confirmed=False)
    with pytest.raises(ValidationError):
        Measurement(value=280, unit="mm", source="photo_estimate", confirmed=True)


def test_contract_rejects_contradictions():
    with pytest.raises(ValidationError):
        ReferenceInput(
            kind="rectangle",
            width_mm=10,
            height_mm=10,
            size_source="ruler",
            size_tolerance_mm=0.5,
        )
    with pytest.raises(ValidationError):
        ReferenceInput(kind="forma_card", width_mm=10, size_tolerance_mm=0.5)
    with pytest.raises(ValidationError):
        OutlineInput(source="sam_box", x1=10, y1=10, x2=5, y2=20)
    with pytest.raises(ValidationError):
        OutlineInput(source="user_polygon", polygon_px=points([(0, 0), (1, 1)]))


def test_printable_card_is_true_size_and_matches_the_detector():
    svg = card_svg()
    assert svg == card_svg()
    assert 'width="200mm"' in svg and "Actual size" in svg and "150 mm" in svg
    for marker_id in MARKER_ORIGINS:
        modules = marker_modules(marker_id)
        assert modules[0].all() and modules[:, 0].all()  # black border
        image = np.kron(1 - modules, np.ones((20, 20), np.uint8)) * 255
        canvas = np.full((200, 200), 255, np.uint8)
        canvas[40:160, 40:160] = image
        _, ids, _ = cv2.aruco.ArucoDetector(DICTIONARY).detectMarkers(canvas)
        assert ids is not None and ids.flatten().tolist() == [marker_id]
    assert PX_PER_MM > 0


@pytest.mark.parametrize("quality", [92, 70])
def test_jpeg_photo_with_generous_box_near_a_marker(quality):
    # Regression from the connected demo: compression noise beside the edge
    # grew the outline by about 10 mm while still claiming a rectangle.
    image, h, _ = scene(tilt=20, yaw=8)
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    p = project(h, SHEET)
    generous = OutlineInput(
        source="manual_box",
        x1=int(p[:, 0].min()) - 30,
        y1=int(p[:, 1].min()) - 25,
        x2=int(p[:, 0].max()) + 30,
        y2=int(p[:, 1].max()) + 25,
    )
    result = estimate(image, make_input(image, generous))
    assert result.outcome == "estimate"
    d = dims(result)
    for name, truth in (("edge_length_mm", 280), ("edge_width_mm", 190)):
        assert_covers(d[name], truth, 2.5)
        assert d[name].sensitivity_low - 1 <= truth <= d[name].sensitivity_high + 1
    assert result.uncertainty.outline_edge_residual_px is not None


def test_ragged_edges_are_never_reported_as_a_rectangle():
    image, h, _ = scene()
    rng = np.random.default_rng(3)
    corners = project(h, SHEET)
    ragged = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        normal = np.array([-(b - a)[1], (b - a)[0]]) / np.linalg.norm(b - a)
        for t in np.linspace(0, 1, 40, endpoint=False):
            ragged.append(a + (b - a) * t + normal * rng.uniform(-8, 8))
    outline = OutlineInput(source="user_polygon", polygon_px=points(ragged))
    result = estimate(image, make_input(image, outline))
    assert result.outcome != "estimate"
    assert all(d.stock_field is None for d in result.dimensions)


def test_evaluation_scores_only_the_evaluation_split(tmp_path):
    import json

    from forma_photo_measure.evaluate import run

    samples = []
    for index, (tilt, yaw) in enumerate([(0, 0), (20, 8), (35, -20), (75, 0)]):
        image, h, _ = scene(tilt=tilt, yaw=yaw, distance=500 if tilt > 60 else 650)
        name = f"scene-{index}.png"
        cv2.imwrite(str(tmp_path / name), image)
        samples.append(
            {
                "id": f"s{index}",
                "split": "calibration" if index == 0 else "evaluation",
                "image": name,
                "stock_material": "cardboard",
                "reference": card_reference().model_dump(mode="json"),
                "outline": box_around(h, SHEET).model_dump(mode="json"),
                "capture": {"shape": "flat", "same_surface_as_reference": True},
                "truth": {
                    "width_mm": 280,
                    "height_mm": 190,
                    "method": "synthetic geometry",
                },
            }
        )
    manifest = {
        "tolerance_mm": 3,
        "tolerance_basis": "synthetic check only",
        "tolerance_chosen_on": "2026-11-04",
        "synthetic": True,
        "samples": samples,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    report = run(tmp_path / "manifest.json")
    assert report["synthetic"] is True
    assert report["calibration_samples"] == 1 and report["evaluation_samples"] == 3
    assert report["accepted"] >= 2
    assert report["wrongly_accepted"] == 0
    assert report["beyond_tolerance"] <= report["accepted"]
    assert report["worst_abs_error_mm"] < 5
    assert 0 <= report["rejection_rate"] <= 1


def test_notched_rectangle_is_not_stock_size():
    image, h, _ = scene()
    notched_mm = [
        (200, 60),
        (330, 60),
        (330, 75),
        (350, 75),
        (350, 60),
        (480, 60),
        (480, 250),
        (200, 250),
    ]
    outline = OutlineInput(
        source="user_polygon", polygon_px=points(project(h, notched_mm))
    )
    result = estimate(image, make_input(image, outline))
    assert result.outcome != "estimate"
    assert all(d.stock_field is None for d in result.dimensions)


def test_drawn_outline_outside_the_photo_is_refused():
    image, h, _ = scene()
    corners = project(h, SHEET)
    corners[1] = (image.shape[1] + 40, corners[1][1])
    result = estimate(
        image,
        make_input(
            image, OutlineInput(source="user_polygon", polygon_px=points(corners))
        ),
    )
    assert result.outcome == "needs_better_photo"
    assert "cut off at the photo edge" in result.request


# Recovery when SAM returns no region (November 4, 2026 live run 4).
def suggest(image, reference=None):
    from forma_photo_measure.suggest import reference_points, suggest_region

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return suggest_region(image, reference_points(gray, reference or card_reference()))


def test_suggested_region_finds_the_sheet_not_the_reference():
    image, h, _ = scene()
    found = suggest(image)
    assert found.reason == "suggested"
    x1, y1, x2, y2 = found.box
    sheet = project(h, SHEET)
    assert x1 <= sheet[:, 0].min() and x2 >= sheet[:, 0].max()
    assert y1 <= sheet[:, 1].min() and y2 >= sheet[:, 1].max()
    result = estimate(
        image,
        make_input(
            image,
            OutlineInput(source="outline_suggestion", x1=x1, y1=y1, x2=x2, y2=y2),
        ),
    )
    found_dims = dims(result)
    assert_covers(found_dims["edge_length_mm"], 280, 3)
    assert_covers(found_dims["edge_width_mm"], 190, 3)


def test_suggested_region_on_a_notched_sheet_stays_irregular():
    notched = [
        (200, 60),
        (300, 60),
        (300, 85),
        (330, 85),
        (330, 60),
        (480, 60),
        (480, 250),
        (200, 250),
    ]
    image, _, _ = scene(outer=notched)
    found = suggest(image)
    assert found.reason == "suggested"
    x1, y1, x2, y2 = found.box
    result = estimate(
        image,
        make_input(
            image,
            OutlineInput(source="outline_suggestion", x1=x1, y1=y1, x2=x2, y2=y2),
        ),
    )
    assert result.outcome == "enclosing_only"
    assert all(d.stock_field is None for d in result.dimensions)


def test_only_the_reference_is_never_suggested():
    image, _, _ = scene(outer=rect_mm(0, 0, 0.1, 0.1))
    found = suggest(image)
    assert found.reason in ("only_reference", "nothing_found")
    assert found.box is None


def test_material_cut_off_at_the_edge_is_not_suggested():
    from forma_photo_measure.suggest import suggest_region

    far = np.array([(700.0, 40.0), (760.0, 40.0), (760.0, 80.0), (700.0, 80.0)])
    image = np.full((600, 800, 3), 200, np.uint8)
    cv2.rectangle(image, (0, 200), (300, 400), (40, 90, 150), -1)
    found = suggest_region(image, far)
    assert (found.reason, found.box) == ("only_cut_off", None)
    blank = suggest_region(np.full((600, 800, 3), 200, np.uint8), far)
    assert (blank.reason, blank.box) == ("nothing_found", None)


def test_no_suggestion_when_the_reference_cannot_be_located():
    # An unlocated card could itself be the most distinct region.
    from forma_photo_measure.suggest import suggest_region

    image, _, _ = scene()
    found = suggest_region(image, np.zeros((0, 2)))
    assert (found.reason, found.box) == ("reference_not_found", None)


def test_a_box_around_the_reference_is_refused_as_material():
    image, h, _ = scene()
    from forma_photo_measure.detect import detect_markers

    corners = np.vstack(
        list(detect_markers(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)).values())
    )
    x1, y1 = np.floor(corners.min(axis=0)).astype(int) - 6
    x2, y2 = np.ceil(corners.max(axis=0)).astype(int) + 6
    result = estimate(
        image,
        make_input(
            image,
            OutlineInput(
                source="sam_box", x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2)
            ),
        ),
    )
    assert result.outcome == "needs_better_photo"
    assert not result.dimensions


def test_a_frame_around_the_reference_is_still_material():
    # The card sits in the frame's opening: the hole is not material.
    frame = rect_mm(5, 5, 200, 140)
    opening = rect_mm(15, 15, 175, 120)
    image, h, _ = scene(outer=frame, holes=[opening], tilt=0, yaw=0)
    from forma_photo_measure.detect import detect_markers

    assert detect_markers(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    corners = project(h, frame)
    outline = OutlineInput(
        source="user_polygon",
        polygon_px=points(corners),
        holes_px=(points(project(h, opening)),),
    )
    result = estimate(image, make_input(image, outline))
    assert "outline_is_reference" not in [d.code for d in result.diagnostics]
