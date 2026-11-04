"""Evaluate photo estimates against independently measured dimensions.

    uv run python -m forma_photo_measure.evaluate path/to/manifest.json

The manifest and photos stay outside git. The tolerance must be chosen from
the intended fabrication tolerance before the evaluation split is run; it is
recorded in the report with its basis. Only the ``evaluation`` split is
scored; ``calibration`` samples are for tuning and are counted separately.
"""

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import Field

from forma_domain.models import ID, Positive, Record, Text
from forma_domain.photo_measurement_contracts import (
    CaptureDeclaration,
    EstimateInput,
    OutlineInput,
    ReferenceInput,
)

from .estimate import estimate


class Truth(Record):
    width_mm: Positive  # longer edge
    height_mm: Positive  # shorter edge
    method: Text  # how it was measured, e.g. "steel rule, 0.5 mm divisions"


class Sample(Record):
    id: ID
    split: Literal["calibration", "evaluation"]
    image: Text  # relative to the manifest
    stock_kind: Literal["sheet", "strip"] = "sheet"
    stock_material: Literal["cardboard", "paperboard", "other_supported"]
    reference: ReferenceInput
    outline: OutlineInput
    capture: CaptureDeclaration
    truth: Truth


class Manifest(Record):
    tolerance_mm: Positive
    tolerance_basis: Text
    tolerance_chosen_on: Text  # date, before the evaluation split was run
    synthetic: bool = False
    samples: tuple[Sample, ...] = Field(min_length=1, max_length=2000)


def _load(path: Path, sample: Sample):
    data = (path.parent / sample.image).read_bytes()
    image = cv2.imdecode(
        np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
    )
    if image is None:
        raise ValueError(f"{sample.id}: image could not be decoded")
    return image, hashlib.sha256(data).hexdigest()


def run(path: Path) -> dict:
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    rows = []
    for sample in manifest.samples:
        if sample.split != "evaluation":
            continue
        image, sha = _load(path, sample)
        data = EstimateInput(
            stock_id="evaluation-stock",
            stock_kind=sample.stock_kind,
            stock_material=sample.stock_material,
            media_id="evaluation-photo",
            media_sha256=sha,
            image_width_px=image.shape[1],
            image_height_px=image.shape[0],
            reference=sample.reference,
            outline=sample.outline,
            capture=sample.capture,
        )
        start = time.perf_counter()
        result = estimate(image, data)
        seconds = time.perf_counter() - start
        row = {"id": sample.id, "outcome": result.outcome, "seconds": seconds}
        if result.outcome == "estimate":
            dims = {d.stock_field: d for d in result.dimensions if d.stock_field}
            errors, covered = [], []
            for field in ("width_mm", "height_mm"):
                d, truth = dims[field], getattr(sample.truth, field)
                errors.append(
                    {
                        "field": field,
                        "abs_mm": abs(d.value - truth),
                        "rel": abs(d.value - truth) / truth,
                        # What the estimate claimed: its displayed precision.
                        "claimed_mm": d.display_step,
                    }
                )
                covered.append(d.sensitivity_low <= truth <= d.sensitivity_high)
            row["errors"] = errors
            row["covered"] = all(covered)
            # Error larger than the fabrication tolerance: usable for
            # exploration at most, never for a fabrication decision.
            row["beyond_tolerance"] = any(
                e["abs_mm"] > manifest.tolerance_mm for e in errors
            )
            # Accepted although the error exceeds both the tolerance and the
            # precision the estimate itself claimed: an unreliable capture.
            row["wrongly_accepted"] = any(
                e["abs_mm"] > max(manifest.tolerance_mm, e["claimed_mm"])
                for e in errors
            )
        rows.append(row)
    accepted = [r for r in rows if "errors" in r]
    abs_errors = [e["abs_mm"] for r in accepted for e in r["errors"]]
    rel_errors = [e["rel"] for r in accepted for e in r["errors"]]
    seconds = [r["seconds"] for r in rows]
    return {
        "synthetic": manifest.synthetic,
        "tolerance_mm": manifest.tolerance_mm,
        "tolerance_basis": manifest.tolerance_basis,
        "tolerance_chosen_on": manifest.tolerance_chosen_on,
        "calibration_samples": sum(s.split == "calibration" for s in manifest.samples),
        "evaluation_samples": len(rows),
        "accepted": len(accepted),
        "rejection_rate": (len(rows) - len(accepted)) / len(rows) if rows else None,
        "beyond_tolerance": sum(r["beyond_tolerance"] for r in accepted),
        "wrongly_accepted": sum(r["wrongly_accepted"] for r in accepted),
        "median_abs_error_mm": statistics.median(abs_errors) if abs_errors else None,
        "worst_abs_error_mm": max(abs_errors) if abs_errors else None,
        "median_rel_error": statistics.median(rel_errors) if rel_errors else None,
        "worst_rel_error": max(rel_errors) if rel_errors else None,
        "sensitivity_range_coverage": (
            sum(r["covered"] for r in accepted) / len(accepted) if accepted else None
        ),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "worst_seconds": max(seconds) if seconds else None,
        "outcomes": {
            o: sum(r["outcome"] == o for r in rows)
            for o in {r["outcome"] for r in rows}
        },
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.manifest), indent=2))


if __name__ == "__main__":
    main()
