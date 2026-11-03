"""Export actual synthetic API outputs for the combined fabrication browser check.

No provider calls, private data or physical results. Output belongs outside git.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for source in (
    "apps/api/src",
    "apps/api/tests",
    "packages/domain/src",
    "packages/compiler/src",
    "packages/renderer/src",
    "packages/replanner/src",
    "packages/fabrication/src",
):
    sys.path.insert(0, str(REPO / source))


def export(directory):
    import pytest
    import test_adapt
    from test_fabrication import assessment, fabrication, preview_fabrication
    from test_plans import AUTH

    from forma_api import fabrication_runtime

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(fabrication_runtime, "ALLOW_SYNTHETIC", True)
        fixture = test_adapt.setup.__wrapped__(directory, monkeypatch)
        client, version, _ = next(fixture)
        try:
            base = f"/api/projects/{version.project_id}"
            data = {
                "project": client.get(base, headers=AUTH).json(),
                "version": version.model_dump(mode="json"),
                "readiness": client.get(
                    base + "/designs/readiness", headers=AUTH
                ).json(),
                "progress": test_adapt.progress(
                    client, version.project_id, version.version_id
                ),
                "report": fabrication(
                    client, version.project_id, version.version_id
                ).json(),
            }
            response = assessment(
                client, version, additional_tools=["scissors"], tools_confirmed=True
            )
            assert response.status_code == 200, response.text
            data["tools_report"] = response.json()
            assert data["tools_report"]["next_operation_id"] == "stand-cut-panels"
            for operation in version.plan.operations[:4]:
                current = test_adapt.report(
                    client, version.project_id, version.plan, operation.id
                )
            data["after_join_progress"] = current
            data["after_join_report"] = fabrication(
                client, version.project_id, version.version_id
            ).json()
            value = next(
                stock["remaining_length_mm"]["value"]
                for stock in current["expected_remaining_stock"]
                if stock["kind"] == "tape"
            )
            data["connector_measurements"] = [
                {"stock_id": "synthetic-tape-stock", "remaining_length_mm": value}
            ]
            response = assessment(
                client,
                version,
                connector_measurements=data["connector_measurements"],
                remaining_confirmed=True,
                additional_tools=["scissors"],
                tools_confirmed=True,
            )
            assert response.status_code == 200, response.text
            data["measured_report"] = response.json()
            assert (
                data["measured_report"]["next_operation_id"]
                == "stand-joint-rear-attach"
            )
            for operation in version.plan.operations[4:6]:
                current = test_adapt.report(
                    client, version.project_id, version.plan, operation.id
                )
            data["repair_progress"] = current
            data["repair_report"] = fabrication(
                client, version.project_id, version.version_id
            ).json()
            response = test_adapt.simulate(
                client, version.plan, current, [test_adapt.patch(version.plan)]
            )
            assert response.status_code == 200, response.text
            data["previews"] = response.json()
            preview = data["previews"]["previews"][0]
            response = preview_fabrication(
                client, version.project_id, preview["preview_id"]
            )
            assert response.status_code == 200, response.text
            data["preview_report"] = response.json()
            assert (
                data["preview_report"]["next_operation_id"]
                == preview["simulation"]["required_undo_operation_ids"][0]
            )
            return data
        finally:
            fixture.close()


def main(output):
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FORMA_DATA_DIR"] = directory
        data = export(Path(directory) / "first")
        data["second"] = export(Path(directory) / "second")
        Path(output).write_text(json.dumps(data), encoding="utf-8")
    print(
        "Exported combined synthetic API reports, confirmations and repair preview; no physical result."
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python fabrication-fixture.py /tmp/forma-fabrication-combined.json"
        )
    main(sys.argv[1])
