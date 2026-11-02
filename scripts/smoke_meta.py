"""Explicit live smoke. Prints metadata only; never prints images or model prose."""

import argparse
import json
import os
import sys
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
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


def _base_report(gateway) -> dict:
    """Metadata header shared by run_smoke and photo-error paths."""
    try:
        forma_version = version("forma_api")
    except PackageNotFoundError:
        forma_version = None
    return {
        "prompt_version": "inventory-spike-v1",
        "schema_version": "observation-v1",
        "runtime": {
            "python": (
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "pydantic": version("pydantic"),
            "forma_api": forma_version,
            "http_client": "stdlib http.client",
        },
        "models": {"spark": gateway.spark, "sam": gateway.sam},
    }


def preflight(args, env) -> list[str]:
    """Pure prerequisite check; never touches the network."""
    blockers = []
    if not env.get("MODEL_API_KEY"):
        blockers.append("MODEL_API_KEY missing")
    image = getattr(args, "image", None)
    if image is None or not Path(image).is_file():
        blockers.append("real team photo missing")
    if not getattr(args, "consented", False):
        blockers.append("photo consent missing")
    if not getattr(args, "live", False):
        blockers.append("explicit --live missing; no network attempted")
    return blockers


def run_smoke(gateway, image, sam_concept) -> tuple[int, dict]:
    """Run Spark then SAM; report metadata and counts only, never private text."""
    report = _base_report(gateway)
    try:
        observation = gateway.propose(
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
    except GatewayError as exc:
        report["status"] = exc.code
        report["traces"] = [asdict(t) for t in gateway.traces]
        return 1, report
    report["spark_image_schema_tool"] = "validated"
    report["label_count"] = len(observation.labels)
    report["question_count"] = len(observation.questions)
    try:
        boxes = gateway.segment(image, sam_concept)
        report["sam"] = "boxes_returned" if boxes else "no_matches_manual_box_required"
        report["box_count"] = len(boxes)
        report["status"] = "ok"
    except GatewayError as exc:
        report["sam"] = exc.code
        report["fallback"] = "manual Box validation available; user must label/correct"
        report["status"] = "sam_failed"
        report["traces"] = [asdict(t) for t in gateway.traces]
        return 3, report
    report["traces"] = [asdict(t) for t in gateway.traces]
    return 0, report


def _sniff_mime(data: bytes) -> str:
    """Sniff MIME from magic bytes; ImageInput remains the authority."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise GatewayError("invalid_image")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--consented", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--sam-concept", default="cardboard sheet")
    args = parser.parse_args(argv)
    blockers = preflight(args, os.environ)
    if blockers:
        print(json.dumps({"status": "blocked", "blockers": blockers}))
        return 2
    gateway = MetaGateway.from_env()
    try:
        if args.image.stat().st_size > 5_000_000:
            raise GatewayError("invalid_image")
        data = args.image.read_bytes()
        image = ImageInput(data, _sniff_mime(data), True)
    except GatewayError as exc:
        report = _base_report(gateway)
        report["status"] = exc.code
        report["traces"] = [asdict(t) for t in gateway.traces]
        print(json.dumps(report))
        return 1
    except OSError:
        report = _base_report(gateway)
        report["status"] = "photo_read_failed"
        report["traces"] = [asdict(t) for t in gateway.traces]
        print(json.dumps(report))
        return 1
    exit_code, report = run_smoke(gateway, image, args.sam_concept)
    print(json.dumps(report))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
