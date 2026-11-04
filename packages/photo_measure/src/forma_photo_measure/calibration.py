"""Lens calibration from several card photos, and its strict binding rule."""

import cv2
import numpy as np

from forma_domain.photo_measurement_contracts import CARD_MARKER_IDS, CameraCalibration

from .card import marker_corners_mm
from .detect import detect_markers


class CalibrationError(ValueError):
    pass


def calibrate_from_card_views(
    images: list[np.ndarray], calibration_id: str, device_label: str
) -> CameraCalibration:
    """Fit a pinhole + radial/tangential model from card photos of one camera.

    Every view must show all four markers and share one exact image size.
    Card scale does not matter for the lens model.
    """

    if not 3 <= len(images) <= 64:
        raise CalibrationError("Calibration needs 3 to 64 card photos")
    sizes = {image.shape[:2] for image in images}
    if len(sizes) != 1:
        raise CalibrationError("All calibration photos must have the same size")
    height, width = sizes.pop()
    object_points, image_points = [], []
    for image in images:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        markers = detect_markers(gray)
        if not all(i in markers for i in CARD_MARKER_IDS):
            raise CalibrationError("Every calibration photo must show all four markers")
        plane = np.vstack([marker_corners_mm(i) for i in CARD_MARKER_IDS])
        object_points.append(np.hstack([plane, np.zeros((16, 1))]).astype(np.float32))
        image_points.append(
            np.vstack([markers[i] for i in CARD_MARKER_IDS]).astype(np.float32)
        )
    rms, matrix, distortion, _, _ = cv2.calibrateCamera(
        object_points, image_points, (width, height), None, None
    )
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(distortion)):
        raise CalibrationError("Calibration did not converge")
    return CameraCalibration(
        calibration_id=calibration_id,
        device_label=device_label,
        image_width_px=width,
        image_height_px=height,
        camera_matrix=tuple(tuple(float(v) for v in row) for row in matrix),
        distortion=tuple(float(v) for v in distortion.reshape(-1)[:5]),
        rms_reprojection_px=float(rms),
        view_count=len(images),
    )


def binding(calibration: CameraCalibration | None, width: int, height: int) -> str:
    """applied, mismatch or uncalibrated. Rotation or resizing breaks the match."""

    if calibration is None:
        return "uncalibrated"
    if (calibration.image_width_px, calibration.image_height_px) != (width, height):
        return "mismatch"
    return "applied"


def undistort(points: np.ndarray, calibration: CameraCalibration) -> np.ndarray:
    matrix = np.array(calibration.camera_matrix, np.float64)
    distortion = np.array(calibration.distortion, np.float64)
    result = cv2.undistortPoints(
        np.asarray(points, np.float64).reshape(-1, 1, 2), matrix, distortion, P=matrix
    )
    return result.reshape(-1, 2)
