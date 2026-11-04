"""Photo-based planar dimension estimates (#177).

An estimate is evidence for exploration, never a measurement. It cannot be
confirmed: recording a ruler value is a separate inventory action with
``source="user_ruler"``. Coordinates are stored-media pixels with the pixel
centre convention (the centre of the top-left pixel is ``(0, 0)``).
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ID, Nonnegative, Positive, Record, Text

METHOD_VERSION = "planar-homography-v1"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Coordinate = Annotated[float, Field(ge=-0.5, le=30000, allow_inf_nan=False)]

# The FORMA reference card: four DICT_4X4_50 markers whose outer corners sit on
# a 150 x 100 mm rectangle, plus printed check lines of the same lengths.
CARD_DICTIONARY = "DICT_4X4_50"
CARD_MARKER_IDS = (20, 21, 22, 23)
CARD_MARKER_MM = 30.0
CARD_WIDTH_MM = 150.0
CARD_HEIGHT_MM = 100.0


class PixelPoint(Record):
    x: Coordinate
    y: Coordinate


class ReferenceInput(Record):
    """What the reference is and how its physical size is known."""

    kind: Literal["forma_card", "aruco_marker", "rectangle"]
    # forma_card: the printed check lines, measured with a ruler after printing.
    printed_check_x_mm: Positive | None = Field(default=None, le=400)
    printed_check_y_mm: Positive | None = Field(default=None, le=400)
    # aruco_marker (outer black square) and rectangle: known outer size.
    width_mm: Positive | None = Field(default=None, le=2000)
    height_mm: Positive | None = Field(default=None, le=2000)
    size_source: Literal["ruler", "published_standard"] | None = None
    # How far the stated size may be from the true size, in millimetres.
    size_tolerance_mm: Nonnegative = Field(le=20)
    aruco_id: int | None = Field(default=None, ge=0, le=49)
    # Required for a rectangle; optional manual correction for markers.
    # Order: the first edge (corner 1 to 2) is the width.
    corners_px: tuple[PixelPoint, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def complete(self):
        if self.kind == "forma_card":
            if self.width_mm or self.height_mm or self.size_source:
                raise ValueError("The card size comes from its printed check lines")
            if self.corners_px and len(self.corners_px) != 16:
                raise ValueError("Correct all sixteen card corners")
        else:
            if self.width_mm is None or self.height_mm is None:
                raise ValueError("Give the reference width and height")
            if self.size_source is None:
                raise ValueError("Say how the reference size is known")
            if self.printed_check_x_mm or self.printed_check_y_mm:
                raise ValueError("Printed check lines belong to the FORMA card")
        if self.kind == "aruco_marker":
            if self.aruco_id is None:
                raise ValueError("Name the marker ID")
            if self.width_mm != self.height_mm:
                raise ValueError("ArUco markers are square")
        elif self.aruco_id is not None:
            raise ValueError("Only a single marker takes an ID")
        if self.kind == "rectangle" and len(self.corners_px) != 4:
            raise ValueError("Mark the four rectangle corners")
        if self.kind == "aruco_marker" and len(self.corners_px) not in (0, 4):
            raise ValueError("Correct all four marker corners")
        return self


class OutlineInput(Record):
    """Where the material is. Boxes are refined; a polygon is used as drawn."""

    source: Literal["sam_box", "manual_box", "user_polygon"]
    x1: int | None = Field(default=None, ge=0)
    y1: int | None = Field(default=None, ge=0)
    x2: int | None = Field(default=None, ge=0)
    y2: int | None = Field(default=None, ge=0)
    polygon_px: tuple[PixelPoint, ...] = Field(default=(), max_length=512)
    holes_px: tuple[tuple[PixelPoint, ...], ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def shape(self):
        box = (self.x1, self.y1, self.x2, self.y2)
        if self.source == "user_polygon":
            if any(v is not None for v in box) or len(self.polygon_px) < 3:
                raise ValueError("A drawn outline needs at least three points")
            if any(len(hole) < 3 or len(hole) > 256 for hole in self.holes_px):
                raise ValueError("Each hole needs 3 to 256 points")
        else:
            if any(v is None for v in box) or self.polygon_px or self.holes_px:
                raise ValueError("A box needs x1, y1, x2 and y2 only")
            if not (self.x1 < self.x2 and self.y1 < self.y2):  # type: ignore[operator]
                raise ValueError("Box corners are out of order")
        return self


Shape = Literal["flat", "curved", "folded", "stacked", "raised", "roll"]


class CaptureDeclaration(Record):
    """What the user states about the scene; a photo cannot establish these."""

    shape: Shape
    same_surface_as_reference: bool


class CameraCalibration(Record):
    """Lens model valid only for the stated device at this exact image size.

    Stored photos carry no EXIF, so FORMA cannot verify the device; the binding
    is the user's statement plus an exact width/height match, uncropped.
    """

    calibration_id: ID
    device_label: Text
    image_width_px: int = Field(gt=0, le=30000)
    image_height_px: int = Field(gt=0, le=30000)
    camera_matrix: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    distortion: tuple[float, float, float, float, float]
    rms_reprojection_px: Nonnegative
    view_count: int = Field(ge=3, le=64)
    crop: Literal["full_frame"] = "full_frame"
    method_version: Literal["card-calibration-v1"] = "card-calibration-v1"


class EstimateInput(Record):
    """Everything an estimate depends on; its digest identifies the estimate."""

    stock_id: ID
    stock_kind: Literal["sheet", "strip", "tape", "cord"]
    stock_material: Literal["cardboard", "paperboard", "other_supported"]
    media_id: ID
    media_sha256: Sha256
    image_width_px: int = Field(gt=0, le=30000)
    image_height_px: int = Field(gt=0, le=30000)
    reference: ReferenceInput
    outline: OutlineInput
    capture: CaptureDeclaration
    calibration: CameraCalibration | None = None


DimensionName = Literal[
    "edge_length_mm",
    "edge_width_mm",
    "enclosing_length_mm",
    "enclosing_width_mm",
    "outline_area_mm2",
    "hole_area_mm2",
]
DIMENSION_DEFINITIONS: dict[str, str] = {
    "edge_length_mm": "Mean of the two longer opposite edges of a four-cornered flat outline.",
    "edge_width_mm": "Mean of the two shorter opposite edges of a four-cornered flat outline.",
    "enclosing_length_mm": "Longer side of the smallest rotated rectangle that encloses the outline. Not usable material.",
    "enclosing_width_mm": "Shorter side of the smallest rotated rectangle that encloses the outline. Not usable material.",
    "outline_area_mm2": "Area inside the outer outline minus holes.",
    "hole_area_mm2": "Total area of holes inside the outline.",
}


class DimensionEstimate(Record):
    name: DimensionName
    definition: Text
    unit: Literal["mm", "mm2"]
    value: float = Field(allow_inf_nan=False)
    # The value rounded to a step no finer than the sensitivity spread supports.
    display_value: float = Field(allow_inf_nan=False)
    display_step: Positive
    # 5th and 95th percentiles of the sensitivity samples (see Uncertainty).
    sensitivity_low: float = Field(allow_inf_nan=False)
    sensitivity_high: float = Field(allow_inf_nan=False)
    # The inventory field this estimate may prefill, if any.
    stock_field: Literal["width_mm", "height_mm"] | None = None


class Uncertainty(Record):
    method: Literal["monte_carlo_sensitivity"] = "monte_carlo_sensitivity"
    samples: int = Field(ge=0)
    reference_corner_sigma_px: Nonnegative
    # Used outline sigma: the stated assumption or, when larger, the measured
    # scatter of traced straight edges (outline_edge_residual_px).
    outline_sigma_px: Nonnegative
    outline_edge_residual_px: Nonnegative | None = None
    reference_size_tolerance_mm: Nonnegative
    # Residual of the fitted transform at all reference points (needs >4 points).
    fit_rms_mm: Nonnegative | None = None
    # Largest error predicting one card marker's corners from the others.
    holdout_max_error_mm: Nonnegative | None = None
    holdout_checks: int = Field(ge=0)
    statement: Text = (
        "Spread of results when the stated inputs vary by the stated amounts."
        " It is a sensitivity analysis, not a calibrated confidence interval."
    )


DiagnosticCode = Literal[
    "reference_not_found",
    "reference_unverified",
    "reference_partial",
    "reference_too_small",
    "reference_blurry",
    "degenerate_reference",
    "steep_angle",
    "low_resolution_at_material",
    "far_from_reference",
    "fit_residual_high",
    "holdout_error_high",
    "no_independent_check",
    "lens_uncorrected",
    "calibration_mismatch",
    "calibration_applied",
    "outline_clipped",
    "outline_box_too_tight",
    "outline_not_found",
    "outline_crosses_horizon",
    "irregular_outline",
    "holes_present",
    "opposite_edges_differ",
    "unsupported_shape",
    "not_on_reference_plane",
    "thickness_not_measurable",
]


class Diagnostic(Record):
    code: DiagnosticCode
    severity: Literal["info", "warning", "blocking"]
    message: Text
    value: float | None = Field(default=None, allow_inf_nan=False)


Outcome = Literal[
    "estimate",
    "enclosing_only",
    "needs_better_photo",
    "needs_manual_measurement",
    "unsupported_shape",
    "reference_not_found",
    "reference_unverified",
]


class PhotoEstimate(Record):
    input_digest: Sha256
    input: EstimateInput
    outcome: Outcome
    dimensions: tuple[DimensionEstimate, ...] = Field(default=(), max_length=6)
    # Reference corners used (detected or corrected) and their planar positions.
    reference_corners_px: tuple[PixelPoint, ...] = Field(default=(), max_length=16)
    reference_corners_mm: tuple[PixelPoint, ...] = Field(default=(), max_length=16)
    outline_px: tuple[PixelPoint, ...] = Field(default=(), max_length=2048)
    holes_px: tuple[tuple[PixelPoint, ...], ...] = Field(default=(), max_length=8)
    calibration_status: Literal["uncalibrated", "applied", "mismatch"]
    uncertainty: Uncertainty | None = None
    diagnostics: tuple[Diagnostic, ...] = Field(default=(), max_length=32)
    assumptions: tuple[Text, ...] = Field(default=(), max_length=12)
    # The one better photo or manual measurement that would help, if any.
    request: Text | None = None
    method_version: Literal["planar-homography-v1"] = METHOD_VERSION
    measurement_status: Literal["photo_estimate_unconfirmed"] = (
        "photo_estimate_unconfirmed"
    )

    @model_validator(mode="after")
    def consistent(self):
        usable = self.outcome in ("estimate", "enclosing_only")
        if usable != bool(self.dimensions):
            raise ValueError("Only estimates carry dimensions")
        if usable and self.uncertainty is None:
            raise ValueError("Estimates carry their uncertainty inputs")
        if not usable and not self.request:
            raise ValueError("A failed estimate says what would help")
        if self.outcome == "enclosing_only" and any(
            d.stock_field for d in self.dimensions
        ):
            raise ValueError("Enclosing dimensions never prefill stock size")
        return self
