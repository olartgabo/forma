"""Offline adapter integration tests. Synthetic fixtures are software evidence only."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from forma_renderer import compile_stand, stand_continuation_blockers
from forma_replanner import simulate_patch

from forma_api import compiler_adapter as adapter
from forma_api.model_gateway import MetaGateway
from forma_api.proposal_service import ProposalService, ProposalSnapshot
from forma_domain import models as m

_fixture_path = (
    Path(__file__).resolve().parents[3] / "packages/renderer/tests/test_stand_manual.py"
)
_spec = importlib.util.spec_from_file_location("adapter_stand_fixture", _fixture_path)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


def setup_case():
    request, parameters, process = _fixtures.fixture()
    compiled = compile_stand(request, parameters, process=process, allow_synthetic=True)
    assert compiled.status == "accepted", compiled.blockers
    evidence = process.evidence + parameters.profile_evidence
    state = ProposalSnapshot(
        project_id=request.project_id,
        version_id=request.version_id,
        stocks=request.stocks,
        profiles=request.joint_profiles,
        constraints=request.constraints,
        plan=compiled.plan,
        evidence=evidence,
    )
    kwargs = dict(
        process=process,
        stand_parameters=parameters,
        profile_evidence=parameters.profile_evidence,
        base_plan=compiled.plan,
        events=(),
        evidence=evidence,
        material_transactions=(),
        historical_plans=(),
        created_at=request.created_at,
        allow_synthetic=True,
    )
    return request, state, kwargs


def patch(state, *, height=150, id="repair-adapter"):
    return m.RepairPatch(
        id=id,
        base_version_id=state.version_id,
        kind="resize_part",
        target_id="stand-base",
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=80,
        height_mm=height,
        angle_deg=None,
        rationale="Synthetic base extension",
    )


class FakeTransport:
    def __init__(self, state, *outputs):
        self.state, self.outputs, self.calls = state, iter(outputs), []

    def post(self, path, payload, timeout):
        self.calls.append(copy.deepcopy(payload))
        if "tools" in payload:
            name = payload["tools"][0]["function"]["name"]
            args = dict(
                project_id=self.state.project_id, version_id=self.state.version_id
            )
            if name == "get_supported_joint_profiles":
                args["profile_ids"] = [p.id for p in self.state.profiles]
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(next(self.outputs))},
                }
            ]
        }


def batch(*candidates):
    return dict(
        candidates=[c.model_dump(mode="json") for c in candidates], questions=[]
    )


def replayed_feedback(fake):
    content = fake.calls[2]["messages"][1]["content"][0]["text"]
    return json.loads(content)["untrusted_context"]["compiler_feedback"][0]["feedback"]


@pytest.mark.parametrize("task", ["design", "repair"])
def test_real_service_accepts_compiler_checked_candidate_without_mutation(task):
    request, state, kwargs = setup_case()
    candidate = request.candidate if task == "design" else patch(state)
    before = copy.deepcopy(
        (
            state.model_dump(),
            {
                k: v.model_dump() if hasattr(v, "model_dump") else v
                for k, v in kwargs.items()
            },
        )
    )
    fake = FakeTransport(state, batch(candidate))
    result = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        task, state, "propose"
    )
    assert result.status == "proposed", result
    assert result.reviews[0].feedback.status == "accepted"
    assert result.proposal.candidates == (candidate,)
    after = (
        state.model_dump(),
        {
            k: v.model_dump() if hasattr(v, "model_dump") else v
            for k, v in kwargs.items()
        },
    )
    assert after == before


@pytest.mark.parametrize("task", ["design", "repair"])
def test_real_rejection_is_exact_and_replayed_to_model(task):
    request, state, kwargs = setup_case()
    if task == "design":
        bad = request.candidate.model_copy(update={"part_width_mm": 10000})
        expected = compile_stand(
            request.model_copy(update={"candidate": bad}),
            kwargs["stand_parameters"],
            process=kwargs["process"],
            allow_synthetic=True,
        )
    else:
        bad = patch(state, height=10000)
        expected = simulate_patch(
            m.ReplannerInput(
                base_plan=state.plan,
                events=(),
                evidence=kwargs["evidence"],
                material_transactions=(),
                remaining_stock=state.stocks,
                patch=bad,
            ),
            process=kwargs["process"],
            allow_synthetic=True,
            family_validator=stand_continuation_blockers,
        )
    assert expected.blockers
    fake = FakeTransport(state, batch(bad), batch())
    result = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        task, state, "propose"
    )
    assert result.reviews[0].feedback.blockers == expected.blockers
    assert result.reviews[0].feedback.status == "blocked"
    assert replayed_feedback(fake)["blockers"] == [
        b.model_dump(mode="json") for b in expected.blockers
    ]
    assert result.proposal is None


@pytest.mark.parametrize(
    "missing,task,fragment",
    [
        ("process", "design", "process"),
        ("process", "repair", "process"),
        ("stand_parameters", "design", "parameters"),
    ],
)
def test_missing_trusted_input_needs_specific_measurement(
    missing, task, fragment, monkeypatch
):
    request, state, kwargs = setup_case()
    kwargs.pop(missing)

    def forbidden(*args, **kwargs):
        pytest.fail("missing trusted input reached compiler or simulator")

    monkeypatch.setattr(adapter, "compile_stand", forbidden)
    monkeypatch.setattr(adapter, "simulate_patch", forbidden)
    candidate = request.candidate if task == "design" else patch(state)
    feedback = adapter.build_validator(**kwargs)(candidate, state)
    assert feedback.status == "needs_measurement"
    assert len(feedback.blockers) == 1
    assert feedback.blockers[0].code == "missing_measurement"
    assert fragment in feedback.blockers[0].message.lower()
    fake = FakeTransport(state, batch(candidate), batch())
    outcome = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        task, state, "propose"
    )
    assert outcome.reviews[0].feedback == feedback
    assert replayed_feedback(fake) == feedback.model_dump(mode="json")


@pytest.mark.parametrize(
    "missing,task", [("base_plan", "repair"), ("created_at", "design")]
)
def test_missing_server_configuration_stops_without_asking_for_measurement(
    missing, task, monkeypatch
):
    request, state, kwargs = setup_case()
    kwargs.pop(missing)

    def forbidden(*args, **kwargs):
        pytest.fail("missing server configuration reached compiler or simulator")

    monkeypatch.setattr(adapter, "compile_stand", forbidden)
    monkeypatch.setattr(adapter, "simulate_patch", forbidden)
    candidate = request.candidate if task == "design" else patch(state)
    with pytest.raises(TypeError):
        adapter.build_validator(**kwargs)(candidate, state)
    fake = FakeTransport(state, batch(candidate), batch())
    outcome = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        task, state, "propose"
    )
    assert outcome.status == "stopped"
    assert outcome.error_code == "compiler_failed"
    assert outcome.questions == ()
    assert outcome.reviews == ()
    # One tool call and one proposal; no compiler feedback round is spent.
    assert len(fake.calls) == 2


def test_repair_uses_bound_plan_without_design_parameters_or_creation_time():
    _, state, kwargs = setup_case()
    kwargs.pop("stand_parameters")
    kwargs.pop("created_at")
    assert adapter.build_validator(**kwargs)(patch(state), state).status == "feasible"


def test_profile_evidence_must_agree_with_bound_history(monkeypatch):
    _, state, kwargs = setup_case()
    kwargs["profile_evidence"] = tuple(
        e.model_copy(update={"description": "Conflicting synthetic record"})
        for e in kwargs["profile_evidence"]
    )

    def forbidden(*args, **kwargs):
        pytest.fail("conflicting profile evidence reached simulator")

    monkeypatch.setattr(adapter, "simulate_patch", forbidden)
    feedback = adapter.build_validator(**kwargs)(patch(state), state)
    assert feedback.status == "blocked"
    assert feedback.blockers == (
        m.Blocker(
            code="invalid_reference",
            message="Trusted profile evidence conflicts with the bound history.",
        ),
    )


def test_design_profile_evidence_must_agree_with_snapshot(monkeypatch):
    # User provenance here is synthetic test data, never physical evidence.
    request, state, kwargs = setup_case()
    confirmed = tuple(
        e.model_copy(
            update={
                "kind": "physical_test",
                "provenance": "user",
                "verification_state": "user_confirmed",
            }
        )
        for e in kwargs["profile_evidence"]
    )
    kwargs["profile_evidence"] = confirmed
    kwargs["allow_synthetic"] = False
    process_evidence = (
        kwargs["process"]
        .evidence[0]
        .model_copy(
            update={"provenance": "user", "verification_state": "user_confirmed"}
        )
    )
    kwargs["process"] = kwargs["process"].model_copy(
        update={"evidence": (process_evidence,)}
    )
    bound = state.model_copy(update={"evidence": (process_evidence, *confirmed)})
    validate = adapter.build_validator(**kwargs)
    assert validate(request.candidate, bound).status == "accepted"
    invalidated = state.model_copy(
        update={
            "evidence": (
                process_evidence,
                *(
                    e.model_copy(update={"verification_state": "invalidated"})
                    for e in confirmed
                ),
            )
        }
    )

    def forbidden(*args, **kwargs):
        pytest.fail("conflicting profile evidence reached compiler")

    monkeypatch.setattr(adapter, "compile_stand", forbidden)
    assert validate(request.candidate, invalidated) == adapter.CandidateFeedback(
        status="blocked",
        blockers=(
            m.Blocker(
                code="invalid_reference",
                message="Trusted profile evidence conflicts with the snapshot evidence.",
            ),
        ),
    )


def test_synthetic_evidence_is_rejected_by_default():
    request, state, kwargs = setup_case()
    kwargs.pop("allow_synthetic")
    feedback = adapter.build_validator(**kwargs)(request.candidate, state)
    assert feedback.status != "accepted"
    assert feedback.blockers


def test_repair_rejects_synthetic_profiles_with_otherwise_verified_process():
    # User provenance here is synthetic test data, never physical evidence.
    _, state, kwargs = setup_case()
    process_evidence = (
        kwargs["process"]
        .evidence[0]
        .model_copy(
            update={"provenance": "user", "verification_state": "user_confirmed"}
        )
    )
    kwargs["process"] = kwargs["process"].model_copy(
        update={"evidence": (process_evidence,)}
    )
    kwargs["evidence"] = (process_evidence, *kwargs["profile_evidence"])
    kwargs["allow_synthetic"] = False
    state = state.model_copy(update={"evidence": kwargs["evidence"]})
    result = adapter.build_validator(**kwargs)(patch(state), state)
    assert result.status == "blocked"
    assert any(
        b.code == "unsupported_profile" and "profile evidence" in b.message
        for b in result.blockers
    )


def test_compiler_exception_is_redacted_in_feedback_and_trace(monkeypatch):
    request, state, kwargs = setup_case()

    def fail(*args, **kwargs):
        raise RuntimeError("SECRET compiler internals")

    monkeypatch.setattr(adapter, "compile_stand", fail)
    fake = FakeTransport(state, batch(request.candidate), batch())
    result = ProposalService(MetaGateway(fake), adapter.build_validator(**kwargs)).run(
        "design", state, "propose"
    )
    assert result.error_code == "compiler_failed"
    assert result.trace.error_code == "compiler_failed"
    assert "SECRET" not in result.model_dump_json()
    assert "SECRET" not in json.dumps(fake.calls)


@pytest.mark.parametrize(
    "change", ["project", "version", "exact_plan", "profile", "history", "stale_patch"]
)
def test_scope_mismatch_blocks_before_simulator(monkeypatch, change):
    request, state, kwargs = setup_case()
    candidate = patch(state)
    if change == "project":
        kwargs["base_plan"] = state.plan.model_copy(
            update={"project_id": "other-project"}
        )
    elif change == "version":
        kwargs["base_plan"] = state.plan.model_copy(
            update={"version_id": "other-version"}
        )
    elif change == "exact_plan":
        kwargs["base_plan"] = state.plan.model_copy(
            update={"compiler_version": "changed"}
        )
    elif change == "profile":
        state = state.model_copy(
            update={
                "profiles": (
                    state.profiles[0].model_copy(update={"limitations": ("changed",)}),
                )
                + state.profiles[1:]
            }
        )
    elif change == "history":
        kwargs["evidence"] = ()
    else:
        candidate = candidate.model_copy(update={"base_version_id": "stale-version"})

    def forbidden(*args, **kwargs):
        pytest.fail("scope mismatch reached simulator")

    monkeypatch.setattr(adapter, "simulate_patch", forbidden)
    feedback = adapter.build_validator(**kwargs)(candidate, state)
    assert feedback.status == "blocked"
    assert feedback.blockers
