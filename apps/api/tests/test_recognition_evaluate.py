"""Recognition scoring rules. A tiny hand-written fixture, not an evaluation."""

import json

import pytest
from pydantic import ValidationError

from forma_api.recognition_evaluate import run


def box(x1, y1, x2, y2):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def write(tmp_path, photos, predictions):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"labelled_by": "test", "labelled_on": "2026-11-04", "photos": photos}
        )
    )
    recorded = tmp_path / "predictions.json"
    recorded.write_text(
        json.dumps(
            {"model": "fixture", "recorded_on": "2026-11-04", "photos": predictions}
        )
    )
    return manifest, recorded


def proposal(identity, b):
    return {"identity": identity, "visible_evidence": "seen", "box": b}


def test_scores_confident_errors_abstentions_other_and_corrections(tmp_path):
    photos = [
        {
            "id": "p1",
            "split": "evaluation",
            "image": "p1.jpg",
            "scene": ["clutter", "similar_pair"],
            "instances": [
                {
                    "id": "a",
                    "category_id": "cardstock",
                    "box": box(0, 0, 0.4, 0.4),
                    "visibility": "full",
                    "similar_to": "thin_packaging_card",
                },
                {
                    "id": "b",
                    "category_id": "felt",
                    "box": box(0.5, 0.5, 0.9, 0.9),
                    "visibility": "partial",
                },
                {
                    "id": "c",
                    "category_id": "other",
                    "box": box(0.5, 0, 0.9, 0.3),
                    "visibility": "full",
                },
                {
                    "id": "d",
                    "category_id": "wire",
                    "box": box(0, 0.6, 0.2, 0.9),
                    "visibility": "full",
                },
            ],
        },
        {
            "id": "tuning",
            "split": "calibration",
            "image": "t.jpg",
            "scene": ["single"],
            "instances": [],
        },
    ]
    predictions = [
        {
            "photo_id": "p1",
            "items": [
                proposal(
                    {
                        "outcome": "catalog",
                        "category_id": "thin_packaging_card",
                        "alternatives": ["cardstock"],
                    },
                    box(0.02, 0.02, 0.4, 0.38),
                ),
                proposal(
                    {"outcome": "uncertain", "alternatives": ["felt"]},
                    box(0.5, 0.5, 0.88, 0.9),
                ),
                proposal(
                    {"outcome": "other", "other_label": "mug"},
                    box(0.5, 0, 0.9, 0.3),
                ),
                proposal(
                    {"outcome": "catalog", "category_id": "sponge"},
                    box(0.95, 0.95, 1, 1),
                ),
            ],
            "reviewed": [
                {
                    "id": "card-a",
                    "name": "Cardstock",
                    "identity": {"outcome": "catalog", "category_id": "cardstock"},
                    "identity_source": "user",
                    "user_fields": ["identity"],
                }
            ],
        }
    ]
    report = run(*write(tmp_path, photos, predictions))
    cats = report["per_category"]
    assert cats["cardstock"]["confident_wrong"] == 1
    assert cats["cardstock"]["confused_with"] == {"thin_packaging_card": 1}
    assert cats["cardstock"]["correct_in_alternatives"] == 1
    assert cats["felt"]["abstained"] == 1
    assert cats["other"]["correct"] == 1 and cats["other"]["called_other"] == 0
    assert cats["wire"]["missed"] == 1
    assert report["spurious_proposals"] == 1
    assert report["confident_wrong_total"] == 1
    assert report["abstained_total"] == 1
    assert report["user_corrected_identity"] == 1
    assert report["calibration_photos"] == 1 and report["photos"] == 1
    assert report["scenes"]["partially_visible_instance"] == {
        "instances": 1,
        "abstained": 1,
    }
    # Three categories seen is not coverage of the catalog.
    assert report["categories_with_real_instances"] == 3
    assert len(report["categories_without_real_instances"]) == 45
    assert report["coverage_claim_allowed"] is False


def test_unpredicted_photos_count_as_missed_and_synthetic_is_refused(tmp_path):
    photos = [
        {
            "id": "p1",
            "split": "evaluation",
            "image": "p1.jpg",
            "scene": ["occlusion"],
            "instances": [
                {
                    "id": "a",
                    "category_id": "sponge",
                    "box": box(0, 0, 1, 1),
                    "visibility": "partial",
                }
            ],
        }
    ]
    report = run(*write(tmp_path, photos, []))
    assert report["unpredicted_photos"] == 1
    assert report["per_category"]["sponge"]["missed"] == 1
    manifest, recorded = write(tmp_path, photos, [])
    data = json.loads(manifest.read_text())
    manifest.write_text(json.dumps({**data, "synthetic": True}))
    with pytest.raises(ValidationError):
        run(manifest, recorded)
