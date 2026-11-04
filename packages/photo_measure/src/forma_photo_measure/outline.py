"""Material outlines in image pixels. Boxes only seed the search."""

from dataclasses import dataclass

import cv2
import numpy as np
from shapely.geometry import Polygon

# Upper bound on the region GrabCut processes; larger crops are downscaled and
# their outline uncertainty grows by the same factor.
MAX_REFINE_PIXELS = 1_500_000
MAX_OUTLINE_POINTS = 2048
GRABCUT_SEED = 177
# Robust colour distance (in surface spreads) that marks a pixel as unlike the
# surface around the box.
SURFACE_DISTANCE = 4.0
# Colour noise floor (Lab units) so compression noise beside an edge on a
# plain surface is not mistaken for material.
JPEG_NOISE_LAB = 6.0


@dataclass(frozen=True)
class Outline:
    outer: np.ndarray  # (N, 2) image pixels, pixel-centre convention
    holes: tuple[np.ndarray, ...]
    sigma_px: float
    # outline_clipped, outline_box_too_tight or outline_not_found
    problem: str | None = None
    # Unsimplified traced boundary for edge fitting; ``outer`` when drawn.
    dense: np.ndarray | None = None


def _polygon_points(polygon: Polygon) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
    outer = np.array(polygon.exterior.coords[:-1], np.float64)
    holes = tuple(np.array(r.coords[:-1], np.float64) for r in polygon.interiors)
    return outer, holes


def from_polygon(outer, holes, sigma_px: float) -> Outline:
    polygon = Polygon(outer, holes)
    if not polygon.is_valid or polygon.area <= 0:
        return Outline(np.zeros((0, 2)), (), sigma_px, "outline_not_found")
    o, h = _polygon_points(polygon)
    return Outline(o, h, sigma_px)


SNAP_REACH_PX = 10.0


def _gradient(lab: np.ndarray) -> np.ndarray:
    smooth = cv2.GaussianBlur(lab, (0, 0), 1.0)
    total = np.zeros(lab.shape[:2], np.float64)
    for channel in range(3):
        gx = cv2.Sobel(smooth[..., channel], cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(smooth[..., channel], cv2.CV_64F, 0, 1, ksize=3)
        total += gx * gx + gy * gy
    return np.sqrt(total).astype(np.float32)


def _snap(points: np.ndarray, gradient: np.ndarray) -> tuple[np.ndarray, bool]:
    """Move each traced point along its normal to the strongest colour edge.

    Segmentation decides which region is material; the edge position comes
    from the image gradient with sub-pixel peak interpolation. Points without
    a clear edge nearby stay where segmentation put them.
    """

    n = len(points)
    if n < 8:
        return points, False
    ahead = np.roll(points, -3, axis=0)
    behind = np.roll(points, 3, axis=0)
    tangent = ahead - behind
    length = np.linalg.norm(tangent, axis=1, keepdims=True)
    tangent = tangent / np.maximum(length, 1e-9)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    offsets = np.arange(-SNAP_REACH_PX, SNAP_REACH_PX + 0.25, 0.5)
    samples = points[:, None, :] + offsets[None, :, None] * normal[:, None, :]
    map_x = samples[..., 0].astype(np.float32)
    map_y = samples[..., 1].astype(np.float32)
    values = cv2.remap(gradient, map_x, map_y, cv2.INTER_LINEAR, borderValue=0.0)
    peak = np.argmax(values, axis=1)
    strength = values[np.arange(n), peak]
    clear = (
        (strength > 0.25 * np.median(strength)) & (peak > 0) & (peak < len(offsets) - 1)
    )
    left = values[np.arange(n), np.clip(peak - 1, 0, len(offsets) - 1)]
    right = values[np.arange(n), np.clip(peak + 1, 0, len(offsets) - 1)]
    curvature = left - 2 * strength + right
    shift = np.divide(
        0.5 * (left - right),
        curvature,
        out=np.zeros_like(curvature),
        where=np.abs(curvature) > 1e-9,
    )
    best = offsets[peak] + np.clip(shift, -1, 1) * 0.5
    moved = points + np.where(clear, best, 0.0)[:, None] * normal
    return moved, bool(np.mean(clear) > 0.5)


def refine_box(
    image: np.ndarray, box: tuple[int, int, int, int], sigma_px: float
) -> Outline:
    """Segment the material inside a box and trace its outer edge and holes."""

    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 < width and 0 <= y1 < y2 < height):
        return Outline(np.zeros((0, 2)), (), sigma_px, "outline_not_found")
    margin = max(8, round(0.08 * max(x2 - x1, y2 - y1)))
    cx1, cy1 = max(0, x1 - margin), max(0, y1 - margin)
    cx2, cy2 = min(width - 1, x2 + margin), min(height - 1, y2 + margin)
    crop = image[cy1 : cy2 + 1, cx1 : cx2 + 1]
    scale = min(1.0, (MAX_REFINE_PIXELS / crop.shape[0] / crop.shape[1]) ** 0.5)
    if scale < 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Seed: the box is probable material, the margin around it probable
    # background (a real background sample that may still flip to material, so
    # a slightly tight box finds the whole piece), and a thin outer border
    # definite background. Material reaching that border means the box cut it.
    inset = 2
    crop_h, crop_w = crop.shape[:2]
    seed_area = (x2 - x1 + 1) * (y2 - y1 + 1) * scale * scale
    mask = np.full(crop.shape[:2], cv2.GC_PR_BGD, np.uint8)
    bx1, by1 = round((x1 - cx1) * scale), round((y1 - cy1) * scale)
    bx2, by2 = round((x2 - cx1) * scale), round((y2 - cy1) * scale)
    # Inside the box, only pixels clearly unlike the surrounding surface start
    # as probable material; a generous box is mostly background.
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float64)
    inside = np.zeros(crop.shape[:2], bool)
    inside[by1 : by2 + 1, bx1 : bx2 + 1] = True
    ring = lab[~inside]
    centre = np.median(ring, axis=0)
    spread = 1.4826 * np.median(np.abs(ring - centre), axis=0) + JPEG_NOISE_LAB
    distance = np.sqrt((((lab - centre) / spread) ** 2).sum(axis=2))
    mask[inside & (distance > SURFACE_DISTANCE)] = cv2.GC_PR_FGD
    if not np.any(mask == cv2.GC_PR_FGD):
        return Outline(np.zeros((0, 2)), (), sigma_px / scale, "outline_not_found")
    mask[:inset, :] = mask[-inset:, :] = cv2.GC_BGD
    mask[:, :inset] = mask[:, -inset:] = cv2.GC_BGD
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(GRABCUT_SEED)
    try:
        cv2.grabCut(crop, mask, None, background, foreground, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return Outline(np.zeros((0, 2)), (), sigma_px / scale, "outline_not_found")
    material = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(
        np.uint8
    )
    kernel = np.ones((3, 3), np.uint8)
    material = cv2.morphologyEx(material, cv2.MORPH_OPEN, kernel)
    material = cv2.morphologyEx(material, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(material, connectivity=8)
    if count < 2:
        return Outline(np.zeros((0, 2)), (), sigma_px / scale, "outline_not_found")
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[largest, cv2.CC_STAT_AREA] < 0.01 * seed_area:
        return Outline(np.zeros((0, 2)), (), sigma_px / scale, "outline_not_found")
    component = np.where(labels == largest, 255, 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(
        component, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
    )
    outer_index = max(
        (i for i in range(len(contours)) if hierarchy[0][i][3] < 0),
        key=lambda i: cv2.contourArea(contours[i]),
    )
    outer = contours[outer_index].reshape(-1, 2).astype(np.float64)
    min_hole = max(25.0, 0.002 * cv2.contourArea(contours[outer_index]))
    holes = [
        contours[i].reshape(-1, 2).astype(np.float64)
        for i in range(len(contours))
        if hierarchy[0][i][3] == outer_index
        and cv2.contourArea(contours[i]) >= min_hole
    ][:8]
    edge = inset + 1
    on_crop_edge = (
        ((outer[:, 0] <= edge) & (cx1 > 0))
        | ((outer[:, 1] <= edge) & (cy1 > 0))
        | ((outer[:, 0] >= crop_w - 1 - edge) & (cx2 < width - 1))
        | ((outer[:, 1] >= crop_h - 1 - edge) & (cy2 < height - 1))
    )

    gradient = _gradient(lab)
    outer, outer_moved = _snap(outer, gradient)
    holes = [_snap(hole, gradient)[0] for hole in holes]

    def to_image(points):
        return points / scale + (cx1, cy1)

    outer_img = to_image(outer)
    problem = None
    border = inset + 1.5
    if np.any(
        (outer_img[:, 0] <= border)
        | (outer_img[:, 1] <= border)
        | (outer_img[:, 0] >= width - 1 - border)
        | (outer_img[:, 1] >= height - 1 - border)
    ):
        problem = "outline_clipped"
    elif np.any(on_crop_edge):
        problem = "outline_box_too_tight"
    # Snapped points sit on the colour edge; unsnapped contours trace boundary
    # pixel centres, whose edge is half a pixel outward.
    polygon = Polygon(outer_img, [to_image(h) for h in holes])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda part: part.area)
    polygon = polygon.buffer(0 if outer_moved else 0.5 / scale, join_style="mitre")
    if polygon.geom_type != "Polygon" or polygon.area <= 0:
        return Outline(np.zeros((0, 2)), (), sigma_px / scale, "outline_not_found")
    tolerance = 0.75 / scale
    simplified = polygon.simplify(tolerance, preserve_topology=True)
    while len(simplified.exterior.coords) > MAX_OUTLINE_POINTS:
        tolerance *= 2
        simplified = polygon.simplify(tolerance, preserve_topology=True)
    o, h = _polygon_points(simplified)
    dense = np.array(polygon.exterior.coords[:-1], np.float64)
    return Outline(o, h, sigma_px / scale, problem, dense)
