"""Score material recognition against labelled real photographs.

    uv run python -m forma_api.recognition_evaluate manifest.json predictions.json

The manifest (labelled truth) and the predictions (recorded proposals, one per
photo, made before scoring) stay outside git with their photos. Nothing here
calls a model: predictions are recorded first, through the consented intake
route, so the score cannot be tuned against the evaluation split.

A category counts as covered only when the evaluation split holds at least one
labelled real instance of it. Synthetic samples are refused.
"""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from forma_domain.material_catalog import (
    CATEGORY_IDS,
    CategoryId,
    ItemProposal,
    RecognizedItem,
    VisibleBox,
)
from forma_domain.models import ID, Record, Text

MATCH_IOU = 0.3


class TruthInstance(Record):
    id: ID
    # "other" for an object outside the catalog.
    category_id: CategoryId | Literal["other"]
    box: VisibleBox
    visibility: Literal["full", "partial"]
    # A visually similar catalog category this instance is paired with, if the
    # photo was taken to test that confusion.
    similar_to: CategoryId | None = None


class Photo(Record):
    id: ID
    split: Literal["calibration", "evaluation"]
    image: Text  # relative to the manifest; never committed
    scene: tuple[
        Literal["clutter", "similar_pair", "occlusion", "outside_catalog", "single"],
        ...,
    ] = Field(min_length=1, max_length=5)
    instances: tuple[TruthInstance, ...] = Field(max_length=64)


class Manifest(Record):
    labelled_by: Text
    labelled_on: Text
    synthetic: Literal[False] = False
    photos: tuple[Photo, ...] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def unique(self):
        ids = [p.id for p in self.photos]
        if len(set(ids)) != len(ids):
            raise ValueError("photo IDs repeat")
        return self


class PhotoPrediction(Record):
    photo_id: ID
    items: tuple[ItemProposal, ...] = Field(max_length=64)
    # Saved cards after the user's review, to count corrections.
    reviewed: tuple[RecognizedItem, ...] = Field(default=(), max_length=64)


class Predictions(Record):
    model: Text
    recorded_on: Text
    photos: tuple[PhotoPrediction, ...]


def iou(a: VisibleBox, b: VisibleBox) -> float:
    w = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    h = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = w * h
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union else 0.0


def _match(truth, items):
    """Greedy one-to-one match by overlap; proposals without a box never match."""
    pairs = sorted(
        (
            (iou(t.box, p.box), ti, pi)
            for ti, t in enumerate(truth)
            for pi, p in enumerate(items)
            if p.box is not None
        ),
        reverse=True,
    )
    used_t, used_p, matches = set(), set(), {}
    for score, ti, pi in pairs:
        if score < MATCH_IOU or ti in used_t or pi in used_p:
            continue
        used_t.add(ti)
        used_p.add(pi)
        matches[ti] = pi
    return matches, used_p


def _blank():
    return {
        "instances": 0,
        "correct": 0,
        "correct_in_alternatives": 0,
        "abstained": 0,
        "called_other": 0,
        "confident_wrong": 0,
        "missed": 0,
        "confused_with": {},
    }


def run(manifest_path: Path, predictions_path: Path) -> dict:
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    predictions = Predictions.model_validate_json(
        predictions_path.read_text(encoding="utf-8")
    )
    by_photo = {p.photo_id: p for p in predictions.photos}
    per_category = {c: _blank() for c in (*CATEGORY_IDS, "other")}
    scenes: dict[str, dict] = {}
    totals = {
        "photos": 0,
        "unpredicted_photos": 0,
        "spurious_proposals": 0,
        "unlocated_proposals": 0,
        "group_proposals": 0,
        "reviewed_cards": 0,
        "user_corrected_identity": 0,
        "user_corrected_other": 0,
    }
    for photo in manifest.photos:
        if photo.split != "evaluation":
            continue
        totals["photos"] += 1
        prediction = by_photo.get(photo.id)
        if prediction is None:
            # Scored as an empty answer, so its misses reach the scene report.
            totals["unpredicted_photos"] += 1
            prediction = PhotoPrediction(photo_id=photo.id, items=())
        items = prediction.items
        matches, used = _match(photo.instances, items)
        totals["unlocated_proposals"] += sum(p.box is None for p in items)
        totals["spurious_proposals"] += sum(
            pi not in used and p.box is not None for pi, p in enumerate(items)
        )
        totals["group_proposals"] += sum(
            p.instance == "group_count_unknown" for p in items
        )
        for card in prediction.reviewed:
            totals["reviewed_cards"] += 1
            if "identity" in card.user_fields:
                totals["user_corrected_identity"] += 1
            if set(card.user_fields) - {"identity"}:
                totals["user_corrected_other"] += 1
        for ti, truth in enumerate(photo.instances):
            row = per_category[truth.category_id]
            row["instances"] += 1
            outcome = "missed"
            if ti not in matches:
                row["missed"] += 1
            else:
                identity = items[matches[ti]].identity
                if identity.outcome == "uncertain":
                    row["abstained"] += 1
                    outcome = "abstained"
                    if truth.category_id in identity.alternatives:
                        row["correct_in_alternatives"] += 1
                elif identity.outcome == "other":
                    if truth.category_id == "other":
                        row["correct"] += 1
                        outcome = "correct"
                    else:
                        row["called_other"] += 1
                        outcome = "called_other"
                elif identity.category_id == truth.category_id:
                    row["correct"] += 1
                    outcome = "correct"
                else:
                    # A specific catalog category that is wrong: the error
                    # that matters most, because it looks like an answer.
                    row["confident_wrong"] += 1
                    outcome = "confident_wrong"
                    row["confused_with"][identity.category_id] = (
                        row["confused_with"].get(identity.category_id, 0) + 1
                    )
                    if truth.category_id in identity.alternatives:
                        row["correct_in_alternatives"] += 1
            for scene in photo.scene:
                s = scenes.setdefault(scene, {"instances": 0})
                s["instances"] += 1
                s[outcome] = s.get(outcome, 0) + 1
            if truth.visibility == "partial":
                s = scenes.setdefault("partially_visible_instance", {"instances": 0})
                s["instances"] += 1
                s[outcome] = s.get(outcome, 0) + 1
    covered = [c for c in CATEGORY_IDS if per_category[c]["instances"]]
    return {
        "synthetic": False,
        "model": predictions.model,
        "recorded_on": predictions.recorded_on,
        "labelled_by": manifest.labelled_by,
        "labelled_on": manifest.labelled_on,
        "match_iou": MATCH_IOU,
        "calibration_photos": sum(p.split == "calibration" for p in manifest.photos),
        **totals,
        "categories_with_real_instances": len(covered),
        "categories_without_real_instances": [
            c for c in CATEGORY_IDS if c not in covered
        ],
        "confident_wrong_total": sum(
            r["confident_wrong"] for r in per_category.values()
        ),
        "abstained_total": sum(r["abstained"] for r in per_category.values()),
        # Coverage may be claimed only with real labelled instances of every
        # category and every scene type; an enum or synthetic test is not it.
        "coverage_claim_allowed": len(covered) == len(CATEGORY_IDS)
        and all(
            scene in scenes
            for scene in (
                "clutter",
                "similar_pair",
                "occlusion",
                "outside_catalog",
                "partially_visible_instance",
            )
        ),
        "per_category": per_category,
        "scenes": scenes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.predictions), indent=2))


if __name__ == "__main__":
    main()
