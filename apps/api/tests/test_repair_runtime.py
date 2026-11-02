import json

import pytest
from fastapi.testclient import TestClient
from test_plans import TOKENS, prepared

from forma_api import repair_runtime
from forma_api.main import create_app
from forma_api.model_gateway import GatewayError
from forma_api.plans import PlanService
from forma_api.projects import ProjectStore
from forma_domain import models as m


@pytest.fixture
def plan(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        project, body, context = prepared(client)
        result = PlanService(
            ProjectStore(tmp_path), allow_synthetic=True
        ).compile_preview("alice", project["id"], body, **context)
        assert result.status == "accepted"
        yield result.version.plan


def patch(plan, **overrides):
    values = dict(
        id="patch-1",
        base_version_id=plan.version_id,
        kind="resize_part",
        target_id=plan.parts[0].id,
        replacement_stock_id=None,
        replacement_profile_id=None,
        width_mm=80,
        height_mm=150,
        angle_deg=None,
        rationale="Resize the part",
    )
    values.update(overrides)
    return m.RepairPatch(**values)


def proposals(*candidates, questions=()):
    return m.RepairProposals(candidates=candidates, questions=questions)


class FakeGateway:
    spark = "muse-spark-1.3"
    max_rounds = 4
    budget = 60

    def __init__(self, result):
        self.result = result
        self.calls = []

    def propose(self, prompt, output, **kwargs):
        self.calls.append((prompt, output, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_valid_each_patch_kind(plan):
    remaining = plan.stocks
    joint = plan.joints[0]
    cases = [
        patch(plan),
        patch(
            plan,
            id="patch-2",
            kind="replace_part",
            replacement_stock_id=plan.stocks[0].id,
            width_mm=None,
            height_mm=None,
        ),
        patch(
            plan,
            id="patch-3",
            kind="replace_joint_profile",
            target_id=joint.id,
            replacement_profile_id=joint.profile_id,
            width_mm=None,
            height_mm=None,
        ),
        patch(
            plan,
            id="patch-4",
            kind="change_angle",
            target_id=plan.version_id,
            width_mm=None,
            height_mm=None,
            angle_deg=55,
        ),
    ]
    for candidate in cases:
        assert repair_runtime.validate_repairs(
            proposals(candidate), plan=plan, expected_remaining_stock=remaining
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_version_id": "version-other"},
        {"target_id": "part-missing"},
        {
            "kind": "replace_part",
            "target_id": "part-missing",
            "replacement_stock_id": "synthetic-sheet",
            "width_mm": None,
            "height_mm": None,
        },
        {
            "kind": "replace_joint_profile",
            "target_id": "joint-missing",
            "replacement_profile_id": "x",
            "width_mm": None,
            "height_mm": None,
        },
        {
            "kind": "change_angle",
            "target_id": "part-wrong",
            "width_mm": None,
            "height_mm": None,
            "angle_deg": 55,
        },
    ],
)
def test_invalid_targets(plan, overrides):
    # Use valid stock where needed; profile-invalid tested separately.
    remaining = plan.stocks
    candidate = patch(plan, **overrides)
    with pytest.raises(GatewayError) as exc:
        repair_runtime.validate_repairs(
            proposals(candidate), plan=plan, expected_remaining_stock=remaining
        )
    assert exc.value.code == "invalid_repair_reference"


def test_invalid_profile_and_stock(plan):
    joint = plan.joints[0]
    bad_profile = patch(
        plan,
        kind="replace_joint_profile",
        target_id=joint.id,
        replacement_profile_id="profile-not-in-plan",
        width_mm=None,
        height_mm=None,
    )
    with pytest.raises(GatewayError) as exc:
        repair_runtime.validate_repairs(
            proposals(bad_profile), plan=plan, expected_remaining_stock=plan.stocks
        )
    assert exc.value.code == "invalid_repair_reference"
    bad_stock = patch(
        plan,
        kind="replace_part",
        replacement_stock_id="stock-missing",
        width_mm=None,
        height_mm=None,
    )
    with pytest.raises(GatewayError) as exc:
        repair_runtime.validate_repairs(
            proposals(bad_stock), plan=plan, expected_remaining_stock=plan.stocks
        )
    assert exc.value.code == "invalid_repair_reference"


def test_duplicates(plan):
    a = patch(plan)
    b = patch(plan)  # same id and exact duplicate
    with pytest.raises(GatewayError):
        repair_runtime.validate_repairs(
            proposals(a, b), plan=plan, expected_remaining_stock=plan.stocks
        )
    c = patch(plan, id="patch-2")  # exact duplicate ignoring id
    with pytest.raises(GatewayError):
        repair_runtime.validate_repairs(
            proposals(a, c), plan=plan, expected_remaining_stock=plan.stocks
        )


def test_empty_and_question_only(plan):
    with pytest.raises(GatewayError) as exc:
        repair_runtime.validate_repairs(
            proposals(), plan=plan, expected_remaining_stock=plan.stocks
        )
    assert exc.value.code == "invalid_repair_empty"
    with pytest.raises(GatewayError):
        repair_runtime.validate_repairs(
            proposals(questions=("  ",)),
            plan=plan,
            expected_remaining_stock=plan.stocks,
        )
    ok = proposals(questions=("Measure the brace?",))
    assert (
        repair_runtime.validate_repairs(
            ok, plan=plan, expected_remaining_stock=plan.stocks
        )
        == ok
    )


def test_context_content_and_size(plan):
    diagnosis = m.DiagnosisProposal(
        visible_observations=("tear visible",),
        hypotheses=(),
        questions_or_measurements=(),
        affected_ids=(plan.parts[0].id,),
        failure_type="torn_slot",
    )
    context = repair_runtime.build_context(
        project_id=plan.project_id,
        project_goal="stand",
        reported_problem="slot tore",
        diagnosis=diagnosis,
        plan=plan,
        completed_operation_ids=(plan.operations[0].id,),
        failed_operation_ids=(),
        expected_remaining_stock=plan.stocks,
    )
    assert context["reported_problem_is_observed_fact"] is False
    assert context["diagnosis_is_unverified_model_output"] is True
    assert context["active_plan"]["version_id"] == plan.version_id
    assert plan.parts[0].id in context["allowed_ids"]["resize_part"]
    assert plan.version_id in context["allowed_ids"]["change_angle"]
    assert context["joint_profile_ids"]
    assert len(json.dumps(context)) < 64000


def test_propose_repairs_one_call_no_image_tool(plan):
    diagnosis = m.DiagnosisProposal(
        visible_observations=("tear",),
        hypotheses=(),
        questions_or_measurements=(),
        affected_ids=(),
        failure_type="unknown",
    )
    context = repair_runtime.build_context(
        project_id=plan.project_id,
        project_goal="stand",
        reported_problem="tore",
        diagnosis=diagnosis,
        plan=plan,
        expected_remaining_stock=plan.stocks,
    )
    gateway = FakeGateway(proposals(patch(plan)))
    result, diagnostics = repair_runtime.propose_repairs(
        gateway, context=context, plan=plan, expected_remaining_stock=plan.stocks
    )
    assert result.candidates[0].id == "patch-1"
    assert diagnostics.status == "ok" and diagnostics.model == "muse-spark-1.3"
    assert diagnostics.usage is not None and diagnostics.usage.model_calls == 0
    assert len(gateway.calls) == 1
    prompt, output, kwargs = gateway.calls[0]
    assert output is m.RepairProposals
    assert "image" not in kwargs and "tool" not in kwargs
    assert kwargs["system_prompt"] == repair_runtime.REPAIR_SYSTEM_PROMPT
    assert "repair" in kwargs["system_prompt"].lower()


def test_propose_repairs_invalid_output_raises(plan):
    gateway = FakeGateway(proposals(patch(plan, target_id="missing")))
    with pytest.raises(GatewayError) as exc:
        repair_runtime.propose_repairs(
            gateway, context={}, plan=plan, expected_remaining_stock=plan.stocks
        )
    assert exc.value.code == "invalid_repair_reference"
    assert repair_runtime.gateway_error_details(exc.value.code) == (
        502,
        "invalid_response",
        "Model provider returned an unusable response; retry",
    )
