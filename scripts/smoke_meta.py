"""Explicit live smoke. Prints metadata only; never prints images or model prose."""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forma_api.model_gateway import GatewayError, ImageInput, MetaGateway, Tool


class InventoryObservation(BaseModel):
    """Spike-only observation, not a competing Stock or measured inventory schema."""

    model_config = ConfigDict(extra="forbid", strict=True)
    labels: list[str] = Field(max_length=12)
    measurement_source: Literal["unknown"]
    questions: list[str] = Field(max_length=8)


class CheckMeasurements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    measurements_confirmed: Literal[False]


class MeasurementResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    needs_measurement: Literal[True] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--consented", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--sam-concept", default="cardboard sheet")
    args = parser.parse_args()
    blockers = []
    if not os.environ.get("MODEL_API_KEY"):
        blockers.append("MODEL_API_KEY missing")
    if not args.image or not args.image.is_file():
        blockers.append("real team photo missing")
    if not args.consented:
        blockers.append("photo consent missing")
    if not args.live:
        blockers.append("explicit --live missing; no network attempted")
    if blockers:
        print(json.dumps({"status": "blocked", "blockers": blockers}))
        return 2
    gateway = MetaGateway.from_env()
    report = {
        "prompt_version": "inventory-spike-v1",
        "schema_version": "observation-v1",
    }
    try:
        if args.image.stat().st_size > 5_000_000:
            raise GatewayError("invalid_image")
        mime = "image/png" if args.image.suffix.lower() == ".png" else "image/jpeg"
        image = ImageInput(args.image.read_bytes(), mime, True)
        gateway.propose(
            "Inspect this consented inventory photo. Call check_measurements with "
            "measurements_confirmed=false, then list visible candidate stock labels and "
            "questions. Measurement source must remain unknown. Do not infer scale.",
            InventoryObservation,
            image=image,
            tool=Tool(
                "check_measurements",
                CheckMeasurements,
                MeasurementResult,
                lambda args: MeasurementResult(),
            ),
        )
        report["spark_image_schema_tool"] = "validated"
        try:
            boxes = gateway.segment(image, args.sam_concept)
            report["sam"] = (
                "boxes_returned" if boxes else "no_matches_manual_box_required"
            )
            report["box_count"] = len(boxes)
        except GatewayError as exc:
            report["sam"] = exc.code
            report["fallback"] = (
                "manual Box validation available; user must label/correct"
            )
    except (GatewayError, OSError) as exc:
        report["status"] = (
            exc.code if isinstance(exc, GatewayError) else "photo_read_failed"
        )
        print(json.dumps(report | {"traces": [asdict(t) for t in gateway.traces]}))
        return 1
    print(json.dumps(report | {"traces": [asdict(t) for t in gateway.traces]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
