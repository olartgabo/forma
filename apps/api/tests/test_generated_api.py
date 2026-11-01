import os
import subprocess
import sys
from pathlib import Path

from forma_api.design_runtime import (
    DesignCandidateResult,
    DesignDiagnostics,
    DesignErrorResponse,
    DesignGenerateRequest,
    DesignGenerateResult,
    ProjectSnapshot,
    SnapshotToolArgs,
)
from forma_api.generate import API_RECORDS, OUTPUT, artifacts
from forma_api.intake_runtime import (
    IntakeDiagnostics,
    IntakeErrorResponse,
    IntakeRequest,
    IntakeResult,
)
from forma_api.proposal_service import IntakeObservation


def test_api_artifact_reuses_domain_types_and_reflects_route_models():
    content = artifacts()[OUTPUT]
    assert artifacts() == artifacts()
    import_line = next(
        line for line in content.splitlines() if line.startswith("import type")
    )
    for domain_type in (
        "Blocker",
        "BuildPlan",
        "Constraints",
        "DesignCandidate",
        "JointProfile",
        "Stock",
    ):
        assert domain_type in import_line
    assert "export type Stock" not in content
    assert "export type Constraints" not in content
    for record in API_RECORDS:
        assert f"export type {record.__name__} = " in content
        for field in record.model_fields:
            assert f'"{field}"' in content
    assert 'readonly "user_confirmed": true' in content
    assert 'readonly "stocks": ReadonlyArray<Stock>' in content


def test_api_artifact_includes_canonical_intake_records():
    content = artifacts()[OUTPUT]
    canonical = {
        IntakeRequest: "forma_api.intake_runtime",
        IntakeResult: "forma_api.intake_runtime",
        IntakeDiagnostics: "forma_api.intake_runtime",
        IntakeErrorResponse: "forma_api.intake_runtime",
        IntakeObservation: "forma_api.proposal_service",
    }
    for record, module in canonical.items():
        assert record in API_RECORDS
        assert record.__module__ == module
        assert f"export type {record.__name__} = " in content
    # The service-owned observation is exported as an API record, not
    # treated as an unknown domain reference or duplicated in contracts.
    assert 'import type { IntakeObservation } from "./contracts";' not in content
    assert 'readonly "measurement_source": "unknown"' in content
    assert 'readonly "labels": ReadonlyArray<string>' in content
    assert 'readonly "questions": ReadonlyArray<string>' in content
    assert 'readonly "provider_transfer_consented"?: boolean' in content
    assert 'readonly "observation": IntakeObservation' in content
    assert 'readonly "diagnostics": IntakeDiagnostics' in content
    for code in (
        "provider_not_configured",
        "provider_authentication",
        "access_denied",
        "rate_limit",
        "timeout",
        "network_error",
        "invalid_response",
        "consent_required",
        "stale_version",
    ):
        assert f'"{code}"' in content


def test_api_artifact_includes_canonical_design_records():
    content = artifacts()[OUTPUT]
    canonical = {
        DesignGenerateRequest: "forma_api.design_runtime",
        DesignGenerateResult: "forma_api.design_runtime",
        DesignCandidateResult: "forma_api.design_runtime",
        DesignDiagnostics: "forma_api.design_runtime",
        DesignErrorResponse: "forma_api.design_runtime",
        ProjectSnapshot: "forma_api.design_runtime",
        SnapshotToolArgs: "forma_api.design_runtime",
    }
    for record, module in canonical.items():
        assert record in API_RECORDS
        assert record.__module__ == module
        assert f"export type {record.__name__} = " in content
    assert 'readonly "provider_context_consented"?: boolean' in content
    assert 'readonly "inventory_revision_id": string' in content
    assert 'readonly "tool_executions": number' in content
    assert '"generation_in_progress"' in content
    assert '"consent_required"' in content


def test_generated_api_matches_checked_in_artifact_without_app_configuration():
    root = Path(__file__).resolve().parents[3]
    for relative, content in artifacts().items():
        assert (root / relative).read_text(encoding="utf-8") == content
    environment = {**os.environ, "FORMA_API_TOKENS": "invalid configuration"}
    subprocess.run(
        [sys.executable, "-m", "forma_api.generate", "--check"],
        cwd=root,
        env=environment,
        check=True,
    )


def test_api_generation_check_rejects_drift(tmp_path):
    # Exercise the command in a copy so the checked-in artifact is never changed.
    source = Path(__file__).resolve().parents[1] / "src" / "forma_api" / "generate.py"
    copied = tmp_path / "apps" / "api" / "src" / "forma_api" / "generate.py"
    copied.parent.mkdir(parents=True)
    copied.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    generated = tmp_path / OUTPUT
    generated.parent.mkdir(parents=True)
    generated.write_text("stale", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(copied), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Stale generated API contracts: " + OUTPUT in result.stderr
