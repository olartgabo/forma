"""Reference detection and observable image-quality measures."""

import cv2
import numpy as np

from .card import DICTIONARY


def detect_markers(gray: np.ndarray) -> dict[int, np.ndarray]:
    """DICT_4X4_50 markers by ID with sub-pixel outer corners (TL, TR, BR, BL)."""

    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(DICTIONARY, parameters)
    corners, ids, _ = detector.detectMarkers(gray)
    found: dict[int, np.ndarray] = {}
    if ids is None:
        return found
    for marker_id, quad in zip(ids.flatten().tolist(), corners):
        # A repeated ID is ambiguous; drop it rather than guess.
        if marker_id in found:
            found[marker_id] = None  # type: ignore[assignment]
        else:
            found[marker_id] = quad.reshape(4, 2).astype(np.float64)
    return {k: v for k, v in found.items() if v is not None}


def _sample(gray: np.ndarray, points: np.ndarray) -> np.ndarray:
    map_x = points[:, 0].astype(np.float32).reshape(1, -1)
    map_y = points[:, 1].astype(np.float32).reshape(1, -1)
    values = cv2.remap(
        gray.astype(np.float32), map_x, map_y, cv2.INTER_LINEAR, borderValue=np.nan
    )
    return values.reshape(-1)


def edge_spread_px(gray: np.ndarray, quad: np.ndarray) -> float | None:
    """Median 10-90 % rise distance across the marker's outer edges, in pixels.

    The marker border is a printed black-to-white step, so a wide rise means
    blur or motion, independent of scene content.
    """

    spreads = []
    centre = quad.mean(axis=0)
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        length = np.linalg.norm(b - a)
        if length < 8:
            continue
        tangent = (b - a) / length
        normal = np.array([-tangent[1], tangent[0]])
        if np.dot((a + b) / 2 - centre, normal) < 0:
            normal = -normal  # point outward, from black to white
        reach = min(10.0, length / 4)
        offsets = np.linspace(-reach, reach, int(reach * 8) + 1)
        for t in (0.35, 0.5, 0.65):
            base = a + (b - a) * t
            profile = _sample(gray, base + offsets[:, None] * normal)
            if np.any(np.isnan(profile)):
                continue
            low, high = np.percentile(profile, 5), np.percentile(profile, 95)
            if high - low < 40:
                continue
            level10 = low + 0.1 * (high - low)
            level90 = low + 0.9 * (high - low)
            above10 = np.argmax(profile >= level10)
            above90 = np.argmax(profile >= level90)
            spreads.append(abs(offsets[above90] - offsets[above10]))
    return float(np.median(spreads)) if spreads else None
