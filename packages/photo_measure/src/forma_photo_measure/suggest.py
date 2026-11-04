"""Deterministic material-region suggestion for a whole photo.

Used when SAM returns no region. It proposes one box around the largest
region that differs from the surface, never the whole photo, the reference or
anything cut off at the photo edge, and keeps it only if the outline search
inside that box succeeds. A suggestion is not a measurement: the user checks
it, and the estimator applies its own checks again.
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from forma_domain.photo_measurement_contracts import CARD_MARKER_IDS, ReferenceInput

from .detect import detect_markers
from .outline import JPEG_NOISE_LAB, SURFACE_DISTANCE, refine_box

MAX_SUGGEST_PIXELS = 1_000_000
MIN_AREA = 0.005  # of the photo
MAX_AREA = 0.85  # of the photo; larger is background or the whole frame
MAX_CANDIDATES = 3

Reason = Literal[
    "suggested",
    "reference_not_found",
    "nothing_found",
    "only_reference",
    "only_cut_off",
    "outline_not_confirmed",
]


@dataclass(frozen=True)
class Suggestion:
    reason: Reason
    box: tuple[int, int, int, int] | None = None
    # Separate regions that passed the size, edge and reference filters.
    candidates: int = 0


def reference_points(gray: np.ndarray, reference: ReferenceInput) -> np.ndarray:
    """Pixel points spanning the whole reference, or an empty array when it
    is not completely located (a partly found card cannot be excluded)."""

    if reference.corners_px:
        return np.array([(p.x, p.y) for p in reference.corners_px], np.float64)
    markers = detect_markers(gray)
    if reference.kind == "forma_card":
        found = [markers[i] for i in CARD_MARKER_IDS if i in markers]
        if len(found) < len(CARD_MARKER_IDS):
            found = []
    elif reference.kind == "aruco_marker" and reference.aruco_id in markers:
        found = [markers[reference.aruco_id]]
    else:
        found = []
    return np.vstack(found).astype(np.float64) if found else np.zeros((0, 2))


def suggest_region(image: np.ndarray, reference_px: np.ndarray) -> Suggestion:
    """One proposed box in source pixels, or the reason there is none.

    Fails closed without the reference: an unlocated reference could itself
    be the most distinct region in the photo."""
    if len(reference_px) < 3:
        return Suggestion("reference_not_found")

    height, width = image.shape[:2]
    scale = min(1.0, (MAX_SUGGEST_PIXELS / height / width) ** 0.5)
    small = (
        cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )
    sh, sw = small.shape[:2]
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float64)
    band = max(3, round(0.03 * min(sh, sw)))
    ring = np.zeros((sh, sw), bool)
    ring[:band, :] = ring[-band:, :] = True
    ring[:, :band] = ring[:, -band:] = True
    surface = lab[ring]
    centre = np.median(surface, axis=0)
    spread = 1.4826 * np.median(np.abs(surface - centre), axis=0) + JPEG_NOISE_LAB
    distance = np.sqrt((((lab - centre) / spread) ** 2).sum(axis=2))
    mask = np.where(distance > SURFACE_DISTANCE, 255, 0).astype(np.uint8)
    size = max(3, round(0.006 * min(sh, sw)) | 1)
    kernel = np.ones((size, size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    # The reference, with a margin, is never material.
    hull = cv2.convexHull((reference_px * scale).astype(np.float32))
    x, y, w, h = cv2.boundingRect(hull)
    pad = round(0.15 * max(w, h)) + size
    hull_mask = np.zeros_like(mask)
    cv2.fillConvexPoly(hull_mask, hull.astype(np.int32), 255)
    hull_mask = cv2.dilate(hull_mask, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    removed_reference = bool(np.any(mask[hull_mask > 0]))
    mask[hull_mask > 0] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    total = sh * sw
    sized, inside = [], []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if not MIN_AREA * total <= area <= MAX_AREA * total:
            continue
        sized.append(index)
        if x <= 1 or y <= 1 or x + w >= sw - 1 or y + h >= sh - 1:
            continue  # cut off at the photo edge: it cannot be measured
        inside.append((int(area), int(x), int(y), int(w), int(h)))
    if not inside:
        if sized:
            return Suggestion("only_cut_off")
        return Suggestion("only_reference" if removed_reference else "nothing_found")
    inside.sort(reverse=True)
    for _, x, y, w, h in inside[:MAX_CANDIDATES]:
        pad = max(4, round(0.04 * max(w, h)))
        box = (
            max(0, int((x - pad) / scale)),
            max(0, int((y - pad) / scale)),
            min(width - 1, int((x + w + pad) / scale)),
            min(height - 1, int((y + h + pad) / scale)),
        )
        if refine_box(image, box, 1.0).problem is None:
            return Suggestion("suggested", box, len(inside))
    return Suggestion("outline_not_confirmed", None, len(inside))
