"""The public example retains typed replies without runtime paths or credentials."""

import importlib.util
import json
from pathlib import Path

import pytest


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_bundle_retains_reply_provenance_and_excludes_store(tmp_path):
    generator = load("generate-pipeline-walkthrough")
    exporter = load("prepare-pipeline-walkthrough")
    source, _ = generator.generate(tmp_path / "source")
    provider = tmp_path / "provider.json"
    typed = {"candidates": [], "questions": ["Please measure the base."]}
    provider.write_text(
        json.dumps(
            {
                "provider_calls": 1,
                "steps": [
                    {
                        "id": "design",
                        "title": "Saved proposal",
                        "engine": "MetaMuse",
                        "status": "returned",
                        "input": {"synthetic": True},
                        "output": {"status": "needs_measurement"},
                        "typed_model_replies": [typed],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    path = exporter.prepare(source, tmp_path / "public", provider)
    raw = path.read_text(encoding="utf-8")
    result = json.loads(raw)
    step = next(step for step in result["steps"] if step["id"] == "muse-design")
    assert step["output"]["validated_model_replies"] == [typed]
    assert step["output"]["runtime_reply"]["status"] == "needs_measurement"
    assert "artifacts" not in result
    assert "C:\\Users\\" not in raw
    assert result["physical_verification"] == "not_attempted"
    assert result["steps"][-1]["id"] == "progress"
    assert (path.parent / "measurement-reference.png").is_file()
    bad = json.loads(provider.read_text())
    bad["steps"][0]["input"]["secret"] = "Bearer forbidden"
    provider.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="private runtime"):
        exporter.prepare(source, tmp_path / "rejected", provider)
