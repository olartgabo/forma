"""Offline runtime checks with a canonical typed fake transport."""

import json

from test_plans import stand_inputs

from forma_api import design_context, design_runtime
from forma_api.design_context import (
    DesignContext,
    FileDesignContextResolver,
    ResolvedDesignContext,
    StaticDesignContextResolver,
)
from forma_api.model_gateway import MetaGateway
from forma_api.plans import PlanService
from forma_api.projects import BuildRequirements, Project, ProjectStore


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, path, payload, timeout):
        self.calls.append((path, json.loads(json.dumps(payload)), timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def tool_call(project_id, revision_id, call_id="call-1"):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "get_project_snapshot",
                                "arguments": json.dumps(
                                    {
                                        "project_id": project_id,
                                        "inventory_revision_id": revision_id,
                                    }
                                ),
                            },
                        }
                    ]
                },
            }
        ]
    }


def final(payload):
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(payload)}}
        ]
    }


def seeded(tmp_path):
    store = ProjectStore(tmp_path)
    stocks, constraints, candidate, parameters, process, profiles = stand_inputs(
        "project-design"
    )
    project = Project(
        id="project-design",
        goal="SYNTHETIC stand",
        revision_id="inventory-design-1",
        stocks=stocks,
        inventory_confirmed=True,
        requirements=BuildRequirements(
            tools=["Synthetic ruler"], constraints=constraints
        ),
    )
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?)",
            (project.id, "alice", project.model_dump_json()),
        )
    context = DesignContext(
        project_id=project.id,
        inventory_revision_id=project.revision_id,
        process=process,
        parameters=parameters,
        joint_profiles=profiles,
        kerf_mm=2,
        edge_margin_mm=4,
    )
    return store, project, candidate, context


def run(store, project, resolved, fake, service=None):
    return design_runtime.generate_designs(
        MetaGateway(fake),
        store=store,
        owner="alice",
        project=project,
        resolved=resolved,
        user_notes="notes",
        plan_service=service or PlanService(store, allow_synthetic=True),
        idempotency_key="design-runtime-1",
    )


def resolve(context, project):
    if isinstance(context, ResolvedDesignContext):
        return context
    return StaticDesignContextResolver(context)(project.id, project.revision_id)


def test_file_resolver_exact_scope_bounded_and_safe(tmp_path):
    _, project, _, context = seeded(tmp_path)
    path = tmp_path / "context.json"
    path.write_text(
        json.dumps({"contexts": [context.model_dump(mode="json")]}), encoding="utf-8"
    )
    resolver = FileDesignContextResolver(path)
    resolved = resolver(project.id, project.revision_id)
    assert resolved.process is not None and resolved.kerf_mm == 2
    wrong = resolver(project.id, "inventory-other")
    assert wrong.process is None and wrong.blockers[0].code == "missing_measurement"
    path.write_text("{secret parser detail", encoding="utf-8")
    invalid = resolver(project.id, project.revision_id)
    assert invalid.blockers[0].code == "invalid_reference"
    assert "secret" not in invalid.blockers[0].message
    assert "context.json" not in invalid.blockers[0].message
    path.write_bytes(b"x" * (design_context.MAX_CONTEXT_BYTES + 1))
    assert (
        resolver(project.id, project.revision_id).blockers[0].code
        == "invalid_reference"
    )


def test_runtime_tool_snapshot_and_real_compile(tmp_path):
    store, project, candidate, context = seeded(tmp_path)
    fake = Fake(
        tool_call(project.id, project.revision_id),
        final({"candidates": [candidate.model_dump(mode="json")], "questions": []}),
    )
    result = run(store, project, resolve(context, project), fake)
    assert result.status == "proposed"
    assert result.candidates[0].status == "accepted"
    assert result.candidates[0].version.candidate_id == candidate.id
    assert result.diagnostics.tool_executions == 1
    assert result.diagnostics.model_rounds == 2
    assert fake.calls[0][1]["tool_choice"]["function"]["name"] == "get_project_snapshot"
    tool_content = fake.calls[1][1]["messages"][-1]["content"]
    snapshot = json.loads(tool_content)
    assert snapshot["inventory_revision_id"] == project.revision_id
    assert "version_id" not in snapshot
    assert snapshot["available_profile_ids"] == list(candidate.profile_ids)
    assert "profile_evidence" not in tool_content
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1


def test_missing_inputs_match_compiler_valid_fixture_by_stock_kind(tmp_path):
    store, project, candidate, context = seeded(tmp_path)
    resolved = resolve(context, project)
    snapshot = design_runtime.build_snapshot(project, resolved)
    # Compiler-valid fixture: sheet remaining length and tape
    # height/thickness are unknown but irrelevant for their kinds.
    assert snapshot.missing_inputs == ()
    sheet, tape = project.stocks
    unknown_sheet_thickness = project.model_copy(
        update={
            "stocks": (
                sheet.model_copy(
                    update={
                        "thickness_mm": sheet.thickness_mm.model_copy(
                            update={"value": None, "confirmed": False}
                        )
                    }
                ),
                tape,
            )
        }
    )
    missing = design_runtime.missing_inputs(unknown_sheet_thickness, resolved)
    assert any("thickness of stock synthetic-sheet" in item for item in missing)
    unknown_tape_length = project.model_copy(
        update={
            "stocks": (
                sheet,
                tape.model_copy(
                    update={
                        "remaining_length_mm": tape.remaining_length_mm.model_copy(
                            update={"value": None, "confirmed": False}
                        )
                    }
                ),
            )
        }
    )
    missing = design_runtime.missing_inputs(unknown_tape_length, resolved)
    assert any(
        "remaining length of stock synthetic-tape-stock" in item for item in missing
    )
    assert not any("height of stock synthetic-tape-stock" in item for item in missing)


def test_runtime_missing_context_returns_questions_without_preview(tmp_path):
    store, project, candidate, context = seeded(tmp_path)
    fake = Fake(
        tool_call(project.id, project.revision_id),
        final({"candidates": [], "questions": ["Measure the sheet thickness."]}),
    )
    result = run(store, project, resolve(None, project), fake)
    assert result.status == "needs_measurement"
    assert result.questions == ("Measure the sheet thickness.",)
    assert result.candidates == ()
    assert result.blockers
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


def test_runtime_invalid_references_cannot_become_preview(tmp_path):
    store, project, candidate, context = seeded(tmp_path)
    bad = candidate.model_copy(update={"stock_ids": ("missing-stock",)})
    fake = Fake(
        tool_call(project.id, project.revision_id),
        final({"candidates": [bad.model_dump(mode="json")], "questions": []}),
    )
    result = run(store, project, resolve(context, project), fake)
    assert result.status == "blocked"
    assert result.candidates[0].blockers[0].code == "invalid_reference"
    assert result.candidates[0].version is None


def test_runtime_default_service_rejects_synthetic_context(tmp_path):
    store, project, candidate, context = seeded(tmp_path)
    fake = Fake(
        tool_call(project.id, project.revision_id),
        final({"candidates": [candidate.model_dump(mode="json")], "questions": []}),
    )
    result = run(
        store, project, resolve(context, project), fake, service=PlanService(store)
    )
    assert result.status == "blocked"
    assert result.candidates[0].status == "blocked"
    assert result.candidates[0].version is None
    with store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
