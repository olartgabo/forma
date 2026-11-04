"""Synthetic camera views of a flat scene. Fixtures only; no accuracy claim."""

import hashlib

import cv2
import numpy as np
from forma_photo_measure import marker_modules
from forma_photo_measure.card import MARKER_ORIGINS

from forma_domain.photo_measurement_contracts import (
    CARD_MARKER_IDS,
    CARD_MARKER_MM,
    CaptureDeclaration,
    EstimateInput,
    OutlineInput,
    PixelPoint,
    ReferenceInput,
)

PX_PER_MM = 4
PLANE_MM = (520, 380)
CARD_AT = (20.0, 20.0)
BACKGROUND = (200, 200, 200)
MATERIAL = (40, 90, 150)  # brown-ish cardboard in BGR


def texture(polygons=(), card=True, single_marker=None, card_scale=1.0):
    w, h = PLANE_MM
    image = np.full((h * PX_PER_MM, w * PX_PER_MM, 3), BACKGROUND, np.uint8)
    for outer, holes, colour in polygons:
        cv2.fillPoly(
            image,
            [np.round(np.array(outer) * PX_PER_MM).astype(np.int32)],
            colour,
            cv2.LINE_AA,
        )
        for hole in holes:
            cv2.fillPoly(
                image,
                [np.round(np.array(hole) * PX_PER_MM).astype(np.int32)],
                BACKGROUND,
                cv2.LINE_AA,
            )
    markers = []
    if card:
        markers = [(i, MARKER_ORIGINS[i], CARD_MARKER_MM) for i in CARD_MARKER_IDS]
    if single_marker is not None:
        markers = [single_marker]
    module_px = None
    for marker_id, (mx, my), side in markers:
        side *= card_scale
        mx, my = mx * card_scale, my * card_scale
        module_px = side / 6 * PX_PER_MM
        x0, y0 = (CARD_AT[0] + mx) * PX_PER_MM, (CARD_AT[1] + my) * PX_PER_MM
        # white quiet zone
        cv2.rectangle(
            image,
            (int(x0 - module_px), int(y0 - module_px)),
            (int(x0 + 7 * module_px), int(y0 + 7 * module_px)),
            (255, 255, 255),
            -1,
        )
        modules = marker_modules(marker_id)
        for r in range(6):
            for c in range(6):
                if modules[r, c]:
                    cv2.rectangle(
                        image,
                        (round(x0 + c * module_px), round(y0 + r * module_px)),
                        (
                            round(x0 + (c + 1) * module_px) - 1,
                            round(y0 + (r + 1) * module_px) - 1,
                        ),
                        (0, 0, 0),
                        -1,
                    )
    return image


def camera(
    tilt_deg=0.0,
    yaw_deg=0.0,
    distance=650.0,
    size=(1600, 1200),
    f=1300.0,
    shift=(0.0, 0.0),
):
    w, h = size
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], np.float64)
    rx = cv2.Rodrigues(np.array([np.radians(tilt_deg), 0, 0]))[0]
    rz = cv2.Rodrigues(np.array([0, 0, np.radians(yaw_deg)]))[0]
    r = rx @ rz
    centre = np.array([PLANE_MM[0] / 2 + shift[0], PLANE_MM[1] / 2 + shift[1], 0.0])
    t = np.array([0, 0, distance]) - r @ centre
    h_mm = k @ np.column_stack([r[:, 0], r[:, 1], t])
    return k, h_mm / h_mm[2, 2]


def render(tex, h_mm, size=(1600, 1200), k=None, distortion=None):
    scale = np.diag([1 / PX_PER_MM, 1 / PX_PER_MM, 1])
    # Map texture pixel centres (i) to plane mm (i + 0.5) / PX_PER_MM.
    offset = np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]])
    h_tex = h_mm @ scale @ offset
    image = cv2.warpPerspective(
        tex, h_tex, size, flags=cv2.INTER_AREA, borderValue=BACKGROUND
    )
    if distortion is not None:
        w, h = size
        grid = (
            np.stack(np.meshgrid(np.arange(w), np.arange(h)), -1)
            .reshape(-1, 1, 2)
            .astype(np.float64)
        )
        ideal = (
            cv2.undistortPoints(grid, k, np.array(distortion), P=k)
            .reshape(h, w, 2)
            .astype(np.float32)
        )
        image = cv2.remap(
            image,
            ideal[..., 0],
            ideal[..., 1],
            cv2.INTER_LINEAR,
            borderValue=BACKGROUND,
        )
    return image


def project(h_mm, points_mm):
    p = (
        np.hstack([np.asarray(points_mm, np.float64), np.ones((len(points_mm), 1))])
        @ h_mm.T
    )
    return p[:, :2] / p[:, 2:]


def box_around(h_mm, outer_mm, margin_px=12, size=(1600, 1200)):
    p = project(h_mm, outer_mm)
    x1, y1 = np.floor(p.min(axis=0) - margin_px).astype(int)
    x2, y2 = np.ceil(p.max(axis=0) + margin_px).astype(int)
    return OutlineInput(
        source="sam_box",
        x1=max(0, int(x1)),
        y1=max(0, int(y1)),
        x2=min(size[0] - 1, int(x2)),
        y2=min(size[1] - 1, int(y2)),
    )


def card_reference(check_x=150.0, check_y=100.0, tolerance=0.5, **extra):
    return ReferenceInput(
        kind="forma_card",
        printed_check_x_mm=check_x,
        printed_check_y_mm=check_y,
        size_tolerance_mm=tolerance,
        **extra,
    )


def make_input(
    image,
    outline,
    reference=None,
    shape="flat",
    same_surface=True,
    kind="sheet",
    calibration=None,
):
    return EstimateInput(
        stock_id="sheet-a",
        stock_kind=kind,
        stock_material="cardboard",
        media_id="media-1",
        media_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
        image_width_px=image.shape[1],
        image_height_px=image.shape[0],
        reference=reference or card_reference(),
        outline=outline,
        capture=CaptureDeclaration(shape=shape, same_surface_as_reference=same_surface),
        calibration=calibration,
    )


def points(array):
    return tuple(PixelPoint(x=float(x), y=float(y)) for x, y in array)


def rect_mm(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
