"""Planar projective geometry: fitting, mapping, checks. No images here."""

import cv2
import numpy as np


class Degenerate(ValueError):
    """The reference points cannot define a plane-to-image transform."""


def fit_homography(image_px: np.ndarray, plane_mm: np.ndarray) -> np.ndarray:
    """Least-squares image-to-plane homography over all correspondences."""

    if len(image_px) < 4 or len(image_px) != len(plane_mm):
        raise Degenerate("at least four corresponding points are required")
    h, _ = cv2.findHomography(
        image_px.astype(np.float64).reshape(-1, 1, 2),
        plane_mm.astype(np.float64).reshape(-1, 1, 2),
        0,
    )
    if h is None or not np.all(np.isfinite(h)) or abs(np.linalg.det(h)) < 1e-15:
        raise Degenerate("reference points are degenerate")
    return h / h[2, 2] if abs(h[2, 2]) > 1e-12 else h


def projective_w(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    return points @ h[2, :2] + h[2, 2]


def apply(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, np.float64).reshape(-1, 2)
    w = projective_w(h, points)
    xy = points @ h[:2, :2].T + h[:2, 2]
    return xy / w[:, None]


def same_side(h: np.ndarray, reference: np.ndarray, points: np.ndarray) -> bool:
    """False when some points lie beyond the plane's horizon line."""

    sign = np.sign(np.median(projective_w(h, reference)))
    return bool(np.all(np.sign(projective_w(h, points)) == sign))


def local_scale(h: np.ndarray, point) -> tuple[float, float]:
    """Singular values of the mapping's Jacobian: mm per pixel, largest first."""

    x, y = point
    a, b, c = h
    w = c[0] * x + c[1] * y + c[2]
    u = a[0] * x + a[1] * y + a[2]
    v = b[0] * x + b[1] * y + b[2]
    jacobian = np.array(
        [
            [(a[0] * w - u * c[0]) / w**2, (a[1] * w - u * c[1]) / w**2],
            [(b[0] * w - v * c[0]) / w**2, (b[1] * w - v * c[1]) / w**2],
        ]
    )
    s = np.linalg.svd(jacobian, compute_uv=False)
    return float(s[0]), float(s[1])


def rms_residual_mm(h: np.ndarray, image_px, plane_mm) -> float:
    error = apply(h, image_px) - plane_mm
    return float(np.sqrt(np.mean(np.sum(error**2, axis=1))))


def holdout_errors_mm(groups: list[tuple[np.ndarray, np.ndarray]]) -> list[float]:
    """Predict each group's points from the others; largest error per group.

    A transform fitted to exactly four points reproduces them perfectly, so
    accuracy is only checked against points the fit did not use.
    """

    errors = []
    for index, (px, mm) in enumerate(groups):
        others_px = np.vstack([g[0] for i, g in enumerate(groups) if i != index])
        others_mm = np.vstack([g[1] for i, g in enumerate(groups) if i != index])
        h = fit_homography(others_px, others_mm)
        errors.append(float(np.max(np.linalg.norm(apply(h, px) - mm, axis=1))))
    return errors


def convex_quad(points: np.ndarray) -> bool:
    """Four points in order forming a convex, non-self-intersecting quad."""

    if len(points) != 4:
        return False
    cross = []
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        u, v = b - a, c - b
        cross.append(u[0] * v[1] - u[1] * v[0])
    return all(v > 0 for v in cross) or all(v < 0 for v in cross)


def min_angle_deg(points: np.ndarray) -> float:
    angles = []
    n = len(points)
    for i in range(n):
        a, b, c = points[i - 1], points[i], points[(i + 1) % n]
        u, v = a - b, c - b
        cos = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
        angles.append(np.degrees(np.arccos(np.clip(cos, -1, 1))))
    return float(min(angles))


def line_intersection(p1, d1, p2, d2):
    matrix = np.array([d1, -d2]).T
    if abs(np.linalg.det(matrix)) < 1e-9:
        raise Degenerate("parallel edges")
    t = np.linalg.solve(matrix, p2 - p1)
    return p1 + t[0] * d1
