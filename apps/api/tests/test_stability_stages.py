"""Actual authorized API state, hypothetical stage numbers; no physical evidence."""

import copy
import sqlite3

from forma_stability.stage import flat_parts_example
from test_plans import AUTH, OTHER
from test_progress import complete
from test_stability_runtime import authorized

pytest_plugins = ["test_stability_route"]


def stage_request(connected):
    client, url, context, directory = connected
    source = authorized(connected)
    progress = complete(client, source.version, 0)
    snapshot = flat_parts_example(source.version.plan, 1).model_dump(mode="json")
    snapshot.update(
        inventory_revision=context["expected_inventory_revision_id"],
        history_cursor=progress["last_event_id"],
    )
    policy = dict(
        policy_id="stage-test",
        version="synthetic-v1",
        length_tolerance_m=1e-9,
        force_tolerance_n=1e-9,
        moment_tolerance_n_m=1e-9,
        relative_tolerance=1e-12,
        required_margin_m=0.0,
        uncertainty_method="analytic_interval",
        evaluation_budget=16,
        required_check_types=["support", "tip"],
        required_case_ids=["stage"],
    )
    return (
        client,
        url.replace("/test/", "/api/projects/").removesuffix("analyses")
        + "stage-analyses",
        dict(
            **(context | {"expected_last_event_id": progress["last_event_id"]}),
            snapshot=snapshot,
            policy=policy,
        ),
        directory,
    )


def test_reported_intermediate_stage_real_evaluator_read_only(connected):
    client, url, body, directory = stage_request(connected)
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        before = tuple(db.iterdump())
    response = client.post(url, headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["hypothetical"] is True
    assert len(result["analysis"]["component_part_ids"]) == 3
    assert len(result["analysis"]["reports"]) == 3
    assert all(r["status"] == "modeled_pass" for r in result["analysis"]["reports"])
    assert result["analysis"]["physical_evidence_ids"] == []
    assert all(
        r["identity"]["inventory_revision"] == body["expected_inventory_revision_id"]
        for r in result["analysis"]["reports"]
    )
    with sqlite3.connect(directory / "projects.sqlite3") as db:
        assert tuple(db.iterdump()) == before


def test_stage_owner_and_history_boundary(connected):
    client, url, body, _ = stage_request(connected)
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, headers=OTHER, json=body).status_code == 404
    for field in ("expected_inventory_revision_id", "expected_last_event_id"):
        assert (
            client.post(url, headers=AUTH, json=body | {field: "stale"}).status_code
            == 409
        )
    for field, value in (
        ("project_id", "foreign"),
        ("inventory_revision", "foreign"),
        ("history_cursor", None),
        ("completed_operation_ids", []),
        ("basis", "observed"),
    ):
        changed = copy.deepcopy(body)
        changed["snapshot"][field] = value
        assert client.post(url, headers=AUTH, json=changed).status_code == 422


def test_stage_input_edit_and_new_history_invalidate(connected):
    client, url, body, _ = stage_request(connected)
    baseline = client.post(url, headers=AUTH, json=body).json()["analysis"]
    edited = copy.deepcopy(body)
    edited["snapshot"]["parts"][0]["mass_kg"] = None
    result = client.post(url, headers=AUTH, json=edited)
    assert result.status_code == 200, result.text
    assert result.json()["analysis"]["snapshot_hash"] != baseline["snapshot_hash"]
    assert any(
        r["status"] != "modeled_pass" for r in result.json()["analysis"]["reports"]
    )
    source = authorized(connected)
    complete(client, source.version, 1)
    assert client.post(url, headers=AUTH, json=body).status_code == 409


def test_stage_supplemental_inputs_cannot_forge_measurement_authority(connected):
    client, url, body, _ = stage_request(connected)
    report = client.post(url, headers=AUTH, json=body).json()["analysis"]
    case = report["inputs"][0]["cases"][0]

    def q(value, unit):
        return dict(
            kind="scalar", value=value, unit=unit, provenance="assumed", confirmed=False
        )

    case["sliding"] = dict(
        contact_id=case["contact_ids"][0],
        normal_force_n=q(0.2, "N"),
        tangential_force_n=q(0.01, "N"),
        friction_coefficient=q(0.5, "1"),
        planar_coulomb_applicable=True,
    )
    case["sliding"]["friction_coefficient"].update(
        provenance="measured", confirmed=True, evidence_ids=["invented"]
    )
    body["snapshot"]["component_loads"] = [case]
    response = client.post(url, headers=AUTH, json=body)
    assert response.status_code == 422
    assert "evidence" in response.text
