"""Software-only Muse/engine integration; no live provider or physical evidence."""

import json

import pytest
from forma_compiler import CutProcess
from test_model_gateway import Fake, final
from test_plans import stand_inputs

from forma_api.design_context import DesignContext, ResolvedDesignContext
from forma_api.model_gateway import GatewayError, ImageInput, MetaGateway
from forma_api.muse_construction import (
    MuseConstructionProposals,
    generate_muse_construction,
)
from forma_api.projects import BuildRequirements, Project


@pytest.fixture
def inputs():
    stocks, constraints, _, parameters, process, profiles = stand_inputs("my-project")
    # These records exercise production validation; descriptions explicitly say
    # test data and no physical event is stored or implied by this conversion.
    process = CutProcess.model_validate(
        process.model_dump()
        | {
            "evidence": [
                e.model_copy(
                    update={
                        "provenance": "user",
                        "verification_state": "user_confirmed",
                        "description": "Software-only process record; not an observation",
                    }
                )
                for e in process.evidence
            ]
        }
    )
    parameters = parameters.model_copy(
        update={
            "profile_evidence": tuple(
                e.model_copy(
                    update={
                        "provenance": "user",
                        "kind": "physical_test",
                        "verification_state": "user_confirmed",
                        "description": "Software-only profile record; no physical test",
                    }
                )
                for e in parameters.profile_evidence
            )
        }
    )
    project = Project(
        id="my-project",
        goal="A small desktop divider",
        revision_id="my-inventory",
        stocks=stocks,
        inventory_confirmed=True,
        requirements=BuildRequirements(
            tools=("Ruler", "Scissors"), constraints=constraints
        ),
    )
    context = ResolvedDesignContext.from_context(
        DesignContext(
            project_id=project.id,
            inventory_revision_id=project.revision_id,
            process=process,
            parameters=parameters,
            joint_profiles=profiles,
        )
    )
    return project, context


def candidate(identifier="option-a", joined=False):
    pieces = [
        dict(
            id="floor",
            name="Base panel",
            role="base",
            vertices_mm=[
                dict(zip(("x", "y", "z"), p))
                for p in [
                    (0.0, 0.0, 0.0),
                    (80.0, 0.0, 0.0),
                    (80.0, 100.0, 0.0),
                    (0.0, 100.0, 0.0),
                ]
            ],
        )
    ]
    connections = []
    if joined:
        pieces.append(
            dict(
                id="extension",
                name="Extension panel",
                role="extension",
                vertices_mm=[
                    dict(zip(("x", "y", "z"), p))
                    for p in [
                        (80.0, 0.0, 0.0),
                        (160.0, 0.0, 0.0),
                        (160.0, 100.0, 0.0),
                        (80.0, 100.0, 0.0),
                    ]
                ],
            )
        )
        connections.append(
            dict(
                id="hinge",
                first_part_id="floor",
                first_edge=1,
                second_part_id="extension",
                second_edge=3,
                stock_id="synthetic-tape-stock",
                profile_id="synthetic-tape-profile",
                length_mm=30.0,
            )
        )
    return dict(
        id=identifier,
        title="Desktop panels",
        rationale="Proposed dimensions must be checked against your materials.",
        stock_ids=["synthetic-sheet", "synthetic-tape-stock"],
        pieces=pieces,
        connections=connections,
    )


def response(*candidates, questions=()):
    value = final(json.dumps(dict(candidates=candidates, questions=questions)))
    value["usage"] = dict(prompt_tokens=100, completion_tokens=200)
    return value


def run(inputs, *responses, image=None):
    transport = Fake(*responses)
    project, context = inputs
    result = generate_muse_construction(
        MetaGateway(transport),
        project=project,
        resolved=context,
        user_notes="Reuse the saved sheet",
        image=image,
    )
    return result, transport


def test_actual_gateway_schema_photo_and_engine_check_are_connected(inputs):
    image = ImageInput(b"\x89PNG\r\n\x1a\nsoftware-test", "image/png", consented=True)
    before = tuple(
        value.model_dump_json() if hasattr(value, "model_dump_json") else value
        for value in inputs[:1]
    )
    result, transport = run(inputs, response(candidate()), image=image)
    assert len(transport.calls) == 1
    _, payload, _ = transport.calls[0]
    assert payload["max_completion_tokens"] == 8192
    assert (
        payload["response_format"]["json_schema"]["schema"]
        == MuseConstructionProposals.model_json_schema()
    )
    content = payload["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    sent = json.loads(content[0]["text"])["untrusted_context"]
    assert sent["goal"] == inputs[0].goal
    assert sent["stocks"][0]["id"] == inputs[0].stocks[0].id
    assert "test_evidence_ids" not in sent["available_profiles"][0]
    assert "profile_evidence" not in sent
    checked = result.candidates[0]
    assert checked.construction.piece_catalog[0].display_name == "Base panel"
    assert checked.construction.piece_catalog[0].annotation.source == "model"
    assert checked.construction.piece_catalog[0].geometry_class == "rectangle"
    assert len(checked.construction.steps) == 2
    assert checked.fabrication_report.order_status == "complete"
    assert checked.fabrication_plan.stocks == inputs[0].stocks
    assert checked.status == result.status == "needs_measurement"
    assert all(
        p.mass_kg is None and not p.contacts
        for p in checked.construction.request.target.snapshot.parts
    )
    assert all(not s.analysis.physical_evidence_ids for s in checked.construction.steps)
    assert not checked.fabrication_report.attached_joint_ids
    assert result.diagnostics.model_rounds == 1
    assert result.diagnostics.usage.model_calls == 1
    assert result.diagnostics.usage.input_tokens == 100
    assert result.diagnostics.usage.output_tokens == 200
    assert before == tuple(
        value.model_dump_json() if hasattr(value, "model_dump_json") else value
        for value in inputs[:1]
    )


def test_model_join_never_claims_user_access_even_with_server_stand_confirmation(
    inputs,
):
    result, transport = run(inputs, response(candidate(joined=True)))
    checked = result.candidates[0]
    assert len(transport.calls) == 1
    assert len(checked.construction.steps) == 4
    assert all(j.confirmed_accessible is None for j in checked.fabrication_plan.joints)
    assert checked.fabrication_report.order_status == "blocked"
    assert checked.status == result.status == "blocked"
    assert any("access" in b.lower() for b in checked.blockers)
    assert not checked.fabrication_report.attached_joint_ids


def test_geometry_feedback_corrects_once_and_preserves_original_failure(inputs):
    broken = candidate()
    broken["pieces"][0]["vertices_mm"][2]["z"] = 50.0
    result, transport = run(inputs, response(broken), response(candidate("option-b")))
    assert len(transport.calls) == 2
    assert len(result.candidates) == 2
    assert result.candidates[0].status == "blocked"
    assert result.candidates[0].construction is None
    assert result.candidates[1].construction is not None
    feedback = json.loads(transport.calls[1][1]["messages"][1]["content"][0]["text"])[
        "untrusted_context"
    ]["engine_feedback"]
    assert feedback["remaining_candidates"] == 1
    assert "Invalid target geometry" in feedback["engine_blockers"][0]
    assert result.diagnostics.model_rounds == 2
    assert result.diagnostics.usage.model_calls == 2


def test_two_bad_candidates_cannot_start_more_model_rounds(inputs):
    first, second = candidate(), candidate("option-b")
    first["stock_ids"] = ["imagined-sheet"]
    second["stock_ids"] = ["imagined-tape"]
    result, transport = run(inputs, response(first, second))
    assert len(transport.calls) == 1
    assert all(
        r.status == "blocked" and r.fabrication_plan is None for r in result.candidates
    )


def test_correction_cannot_exceed_total_candidate_budget(inputs):
    broken = candidate()
    broken["stock_ids"] = ["imagined-sheet"]
    result, transport = run(
        inputs, response(broken), response(candidate("option-b"), candidate("option-c"))
    )
    assert len(transport.calls) == 2
    assert len(result.candidates) == 1
    assert "one-candidate limit" in result.questions[0]


def test_stock_shortage_is_feedback_not_new_inventory(inputs):
    too_large = candidate()
    too_large["pieces"][0]["vertices_mm"][1]["x"] = 800.0
    too_large["pieces"][0]["vertices_mm"][2]["x"] = 800.0
    result, transport = run(
        inputs,
        response(too_large),
        response(questions=["Can you provide a larger measured sheet?"]),
    )
    assert len(transport.calls) == 2
    assert result.candidates[0].fabrication_plan is None
    assert any("no allocation found" in b for b in result.candidates[0].blockers)
    assert result.questions == ("Can you provide a larger measured sheet?",)


def test_missing_context_returns_geometry_with_blockers_without_repeated_spending(
    inputs,
):
    project, _ = inputs
    transport = Fake(response(candidate()))
    result = generate_muse_construction(
        MetaGateway(transport),
        project=project,
        resolved=ResolvedDesignContext.missing("Measure the cutting process"),
    )
    assert len(transport.calls) == 1
    assert result.candidates[0].construction is not None
    assert result.candidates[0].fabrication_plan is None
    assert "Measure the cutting process" in result.candidates[0].blockers
    assert result.candidates[0].status == result.status == "blocked"


@pytest.mark.parametrize("missing", ["inventory", "tools", "process"])
def test_manufacturing_blockers_cannot_be_downgraded_to_mechanical_unknowns(
    inputs, missing
):
    project, context = inputs
    if missing == "inventory":
        project = project.model_copy(update={"inventory_confirmed": False})
    elif missing == "tools":
        project = project.model_copy(
            update={
                "requirements": project.requirements.model_copy(update={"tools": ()})
            }
        )
    else:
        context = ResolvedDesignContext(
            process=None,
            parameters=context.parameters,
            joint_profiles=context.joint_profiles,
        )
    result, transport = run((project, context), response(candidate()))
    assert len(transport.calls) == 1
    assert result.candidates[0].construction is not None
    assert result.candidates[0].status == result.status == "blocked"


def test_questions_alone_never_imply_a_checked_construction(inputs):
    result, _ = run(
        inputs, response(questions=["That goal is outside supported desktop fixtures."])
    )
    assert result.candidates == ()
    assert result.status == "blocked"


@pytest.mark.parametrize(
    "extra",
    [
        {"mass_kg": 1},
        {"confirmed_accessible": True},
        {"completed_operation_ids": ["cut"]},
        {"evidence": []},
    ],
)
def test_model_cannot_add_measurement_confirmation_or_history_fields(inputs, extra):
    proposal = candidate()
    proposal.update(extra)
    with pytest.raises(GatewayError) as error:
        run(inputs, response(proposal))
    assert error.value.code == "invalid_proposal"


def test_unconsented_image_never_reaches_transport(inputs):
    transport = Fake(response(candidate()))
    with pytest.raises(GatewayError) as error:
        generate_muse_construction(
            MetaGateway(transport),
            project=inputs[0],
            resolved=inputs[1],
            image=ImageInput(b"\x89PNG\r\n\x1a\ntest", "image/png"),
        )
    assert error.value.code == "image_consent_required"
    assert transport.calls == []


def test_unknown_provider_outcome_is_not_hidden_by_a_failed_first_candidate(inputs):
    bad = candidate()
    bad["stock_ids"] = ["imaginary"]
    with pytest.raises(GatewayError) as error:
        run(inputs, response(bad), GatewayError("timeout"))
    assert error.value.code == "timeout"


def test_active_build_cannot_use_new_build_proposal_runtime(inputs):
    project, context = inputs
    transport = Fake()
    with pytest.raises(ValueError, match="history-aware"):
        generate_muse_construction(
            MetaGateway(transport),
            project=project.model_copy(update={"active_version_id": "active-v1"}),
            resolved=context,
        )
    assert not transport.calls
