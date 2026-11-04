# Photo measurement

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #177. Offline and deterministic;
no provider, database or UI dependency. Never confirms a value.

`estimate(image, EstimateInput) -> PhotoEstimate` measures one flat sheet or
strip lying on the same plane as one reference. Contracts live in
`forma_domain.photo_measurement_contracts`.

| Reference | Points | Independent check | Size from |
| --- | --- | --- | --- |
| FORMA card (`card_svg()`) | 16 (four 30 mm DICT_4X4_50 markers, IDs 20–23, outer corners on 150 × 100 mm) | Each marker predicted from the other three | Printed check lines measured with a ruler |
| One ArUco marker | 4 | None (reported) | Stated side, `ruler` or `published_standard` |
| User-marked rectangle | 4 | None (reported) | Stated width and height |

Pipeline: decode stored pixels → optional lens correction (only when the
calibration's width/height match exactly) → reference corners (sub-pixel ArUco
or user corners) → least-squares homography → outline (box: surface-colour
seeded GrabCut, colour-edge snapping, holes kept; polygon: as drawn) →
dimensions → Monte Carlo sensitivity (200 samples, seeded by the input digest).

## Dimension definitions

| Name | Meaning | May prefill stock |
| --- | --- | --- |
| `edge_length_mm` / `edge_width_mm` | Mean of opposite edges of a four-cornered, square-cornered, straight-edged flat outline | Yes, as unconfirmed `photo_estimate` (`width_mm` = longer) |
| `enclosing_length_mm` / `enclosing_width_mm` | Smallest rotated rectangle around the outline | Never |
| `outline_area_mm2`, `hole_area_mm2` | Outline area minus holes; total hole area | Never |

Thickness, strength, mass, friction, hidden damage and remaining tape length
are never estimated. Tape, cord and `curved`, `folded`, `stacked`, `raised` or
`roll` declarations return `unsupported_shape`.

## Outcomes and capture rules

Outcomes: `estimate`, `enclosing_only`, `needs_better_photo`,
`needs_manual_measurement`, `unsupported_shape`, `reference_not_found`,
`reference_unverified`. Every non-estimate carries one concrete request.

`RULES` in `estimate.py` holds the capture rules, chosen before any real-photo
evaluation: reference side ≥ 25 px (warn < 50), marker edge 10–90 % rise ≤ 7 px
(warn > 3.5), foreshortening ratio ≤ 6 (warn > 3), ≤ 2.5 mm per pixel at the
material (warn > 1), fit RMS ≤ 1.5 mm, hold-out error ≤ 3 mm, sensitivity
half-width ≤ 10 % of the value, edge scatter ≤ 2 px for a rectangle, opposite
edges within max(2 mm, 2 %), corners within 3° of square. Displayed values are
rounded to the smallest of 0.5/1/2/5/10/20/50 mm covering the sensitivity
half-width and hold-out error.

A photo cannot prove the material is flat, uncovered or on the reference plane;
those are the user's declarations and are listed as assumptions.

## Calibration

`calibrate_from_card_views` fits a lens model from 3–64 photos of the card from
one camera at one size. `binding()` applies it only to identical width/height;
stored photos carry no EXIF, so the device is the user's statement. The API does
not yet store calibrations; estimates run `uncalibrated` and say so.

## Evaluation

`python -m forma_photo_measure.evaluate manifest.json` scores the `evaluation`
split of a private manifest against independent measurements, using a tolerance
recorded with its basis before the run. See the
[handoff](../../docs/handoffs/issue-177-photo-measurement.md).
