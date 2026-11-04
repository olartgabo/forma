"""Finite, journaled synthetic runtime walkthrough. No production writes/retries."""

import argparse
import base64
import importlib.util
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

from forma_renderer import compile_stand, stand_continuation_blockers
from forma_replanner import simulate_patch

from forma_api import diagnosis_runtime, repair_runtime
from forma_api.design_context import DesignContext, ResolvedDesignContext
from forma_api.design_runtime import (
    DESIGN_PROMPT,
    DESIGN_SYSTEM_PROMPT,
    ProjectSnapshot,
    SnapshotToolArgs,
    build_snapshot,
    validate_candidate_references,
)
from forma_api.intake_runtime import observe_photo
from forma_api.model_gateway import (
    GatewayError,
    ImageInput,
    MetaGateway,
    MetaHTTP,
    Tool,
)
from forma_api.projects import Project
from forma_domain.models import (
    BuildPlan,
    CompilerInput,
    DesignProposals,
    ReplannerInput,
)

spec = importlib.util.spec_from_file_location(
    "runtime_smoke", Path(__file__).with_name("runtime-board-smoke.py")
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
now, append, load_key = smoke.now, smoke.append, smoke.load_key


def serial(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    return value


class ReservedTransport:
    """Only this run's uncertain outcomes halt it; historic journals are untouched."""

    def __init__(self, transport, directory, authorization):
        self.transport, self.directory, self.authorization = (
            transport,
            directory,
            authorization,
        )
        self.calls, self.halted, self.stage = 0, False, "intake"
        self.usage = []

    def post(self, path, payload, timeout):
        if self.halted or self.calls >= self.authorization["max_calls"]:
            raise GatewayError("runtime_run_halted")
        remaining = (
            smoke.datetime.fromisoformat(self.authorization["expires_at"]) - now()
        ).total_seconds()
        if remaining <= 0:
            raise GatewayError("runtime_window_expired")
        model = payload.get("model")
        if self.stage not in {
            "intake",
            "design",
            "diagnosis",
            "repair",
            "segmentation",
        }:
            raise GatewayError("runtime_scope_violation")
        if (model, path) not in {
            ("muse-spark-1.3", "/chat/completions"),
            ("sam-3.1", "/responses"),
        }:
            raise GatewayError("runtime_scope_violation")
        if (model == "sam-3.1") != (self.stage == "segmentation"):
            raise GatewayError("runtime_scope_violation")
        if payload.get("tools") and (
            self.stage != "design"
            or [t.get("function", {}).get("name") for t in payload["tools"]]
            != ["get_project_snapshot"]
        ):
            raise GatewayError("runtime_scope_violation")
        payload = dict(payload)
        if model == "muse-spark-1.3":
            payload.update(max_completion_tokens=8192, reasoning_effort="low")
        text = json.dumps(payload, allow_nan=False)
        import re

        for url in re.findall(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", text):
            if len(base64.b64decode(url.split(",", 1)[1], validate=True)) > 5_000_000:
                raise GatewayError("runtime_input_limit")
            text = text.replace(url, "")
        if len(text.encode()) > 48_000:
            raise GatewayError("runtime_input_limit")
        rid = uuid.uuid4().hex
        append(
            self.directory / "ledger.jsonl",
            dict(
                event="reserved",
                id=rid,
                stage=self.stage,
                model=model,
                max_input_tokens=64_000,
                max_output_tokens=8192,
                request_bytes=len(json.dumps(payload).encode()),
            ),
        )
        self.calls += 1
        start = time.monotonic()
        try:
            result = self.transport.post(path, payload, min(timeout, remaining, 120))
            if len(json.dumps(result).encode()) > 2_000_000:
                raise GatewayError("response_too_large")
            usage = result.get("usage")
            if not isinstance(usage, dict):
                raise GatewayError("runtime_usage_unknown")
            counts = [
                usage.get("prompt_tokens", usage.get("input_tokens")),
                usage.get("completion_tokens", usage.get("output_tokens")),
            ]
            if any(type(v) is not int or v < 0 for v in counts):
                raise GatewayError("runtime_usage_unknown")
            record = dict(
                event="settled",
                id=rid,
                stage=self.stage,
                model=model,
                actual_provider_usage=usage,
                elapsed_ms=round((time.monotonic() - start) * 1000),
            )
            append(self.directory / "ledger.jsonl", record)
            self.usage.append(record)
            return result
        except BaseException as exc:
            self.halted = True
            code = exc.code if isinstance(exc, GatewayError) else "unclassified"
            append(
                self.directory / "ledger.jsonl",
                dict(
                    event="unknown",
                    id=rid,
                    stage=self.stage,
                    failure_code=code,
                    action="HALT; reconcile before retry",
                ),
            )
            raise GatewayError("runtime_outcome_unknown") from None


class CapturingGateway(MetaGateway):
    """Retain validated final typed replies, never raw provider bodies."""

    def propose(self, *args, **kwargs):
        reply = super().propose(*args, **kwargs)
        self.replies.append(serial(reply))
        return reply


def run(snapshot, image, content_type, directory, transport):
    artifacts = snapshot["artifacts"]
    project = Project.model_validate(artifacts["project"])
    plan = BuildPlan.model_validate(snapshot["plan"])
    context = DesignContext.model_validate(artifacts["design_context"])
    resolved = ResolvedDesignContext.from_context(context)
    gateway = CapturingGateway(
        transport, max_rounds=2, max_retries=0, timeout=120, budget=120
    )
    gateway.replies = []
    steps, tools = [], []
    notice = "SYNTHETIC software test. Photo objects are separate reference imagery and do not verify the stand inventory, measurements, damage or physical results."

    def step(sid, title, engine, inputs, function):
        transport.stage = sid
        entry = dict(id=sid, title=title, engine=engine, input=inputs)
        before = len(gateway.replies)
        if transport.halted:
            entry.update(
                status="not_attempted",
                output=None,
                error={"code": "run_halted_after_unknown"},
            )
            steps.append(entry)
            return None
        try:
            value = function()
            entry.update(status="returned", output=serial(value))
        except Exception as exc:
            entry.update(
                status="error",
                output=None,
                error={
                    "code": exc.code
                    if isinstance(exc, GatewayError)
                    else type(exc).__name__
                },
            )
            value = None
        entry["typed_model_replies"] = gateway.replies[before:]
        if sid == "design":
            entry["tool_diagnostics"] = tools
        steps.append(entry)
        save()
        return value

    def save():
        actual = [record["actual_provider_usage"] for record in transport.usage]
        report = dict(
            steps=steps,
            provider_calls=transport.calls,
            usage=transport.usage,
            actual_usage_totals=dict(
                input_tokens=sum(
                    item.get("prompt_tokens", item.get("input_tokens", 0))
                    for item in actual
                ),
                output_tokens=sum(
                    item.get("completion_tokens", item.get("output_tokens", 0))
                    for item in actual
                ),
                images_processed=sum(
                    item.get("images_processed", 0) for item in actual
                ),
            ),
            halted=transport.halted,
            physical_verification="not_attempted",
            notice=notice,
            relationship_to_engine_snapshot="Canonical engine stand was pre-existing deterministic output, not authored by this model. Model design candidates below are separately compiled against synthetic context; no proposal is approved or saved as physical work.",
        )
        (directory / "provider-steps.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    step(
        "intake",
        "Observe synthetic reference materials",
        "MetaMuse observe_photo",
        {"classification": notice},
        lambda: observe_photo(
            gateway,
            project_goal=project.goal + " " + notice,
            image_data=image,
            content_type=content_type,
        ),
    )

    def design():
        def read(args):
            if (
                args.project_id != project.id
                or args.inventory_revision_id != project.revision_id
            ):
                raise GatewayError("invalid_tool_scope")
            result = build_snapshot(project, resolved)
            tools.append(
                dict(
                    tool="get_project_snapshot",
                    arguments=serial(args),
                    result=serial(result),
                )
            )
            return result

        proposals = gateway.propose(
            DESIGN_PROMPT,
            DesignProposals,
            tool=Tool("get_project_snapshot", SnapshotToolArgs, ProjectSnapshot, read),
            system_prompt=DESIGN_SYSTEM_PROMPT,
            context=dict(
                project_id=project.id,
                inventory_revision_id=project.revision_id,
                project_goal=project.goal,
                user_notes=notice
                + " Propose at least one candidate only if the supplied synthetic data suffices; use the configured stand geometry, sheet and tape.",
            ),
        )
        results = []
        for candidate in proposals.candidates:
            blockers = validate_candidate_references(
                candidate, build_snapshot(project, resolved)
            )
            if blockers:
                results.append(
                    dict(
                        candidate_id=candidate.id,
                        status="blocked",
                        blockers=serial(blockers),
                    )
                )
                continue
            request = CompilerInput(
                project_id=project.id,
                version_id="muse-preview-" + candidate.id,
                created_at=now(),
                candidate=candidate,
                stocks=project.stocks,
                joint_profiles=context.joint_profiles,
                constraints=project.requirements.constraints,
                kerf_mm=context.kerf_mm,
                edge_margin_mm=context.edge_margin_mm,
                process_evidence_ids=tuple(e.id for e in context.process.evidence),
            )
            results.append(
                serial(
                    compile_stand(
                        request,
                        context.parameters,
                        process=context.process,
                        allow_synthetic=True,
                    )
                )
            )
        return dict(
            proposals=serial(proposals),
            tool_diagnostics=tools,
            compiler_results=results,
        )

    step(
        "design",
        "Read saved context and compile model candidates",
        "MetaMuse plus actual compile_stand",
        {"synthetic_context_only": True},
        design,
    )
    problem = "SYNTHETIC scenario, not photo evidence: suppose stand-base needs 10mm more depth before any cuts. All operation history is empty. The reference materials photo does not depict an assembled failure. Ask what is missing; never claim visible damage."
    diagnosis_context = diagnosis_runtime.build_context(
        project_id=project.id,
        revision_id=project.revision_id,
        project_goal=project.goal,
        reported_problem=problem,
        stocks=project.stocks,
        plan=plan,
        current_operation_id=plan.operations[0].id,
    )
    diagnosis = step(
        "diagnosis",
        "Separate hypothetical failure from visible image",
        "MetaMuse diagnose_photo",
        {"reported_problem": problem, "physical_history": []},
        lambda: diagnosis_runtime.diagnose_photo(
            gateway,
            image_data=image,
            content_type=content_type,
            context=diagnosis_context,
            plan=plan,
        ),
    )

    def repair():
        if diagnosis is None:
            raise GatewayError("diagnosis_unavailable")
        ctx = repair_runtime.build_context(
            project_id=project.id,
            project_goal=project.goal,
            reported_problem=problem,
            diagnosis=diagnosis[0],
            plan=plan,
            expected_remaining_stock=plan.stocks,
        )
        proposals, diagnostics = repair_runtime.propose_repairs(
            gateway, context=ctx, plan=plan, expected_remaining_stock=plan.stocks
        )
        simulations = []
        for candidate in proposals.candidates:
            inputs = ReplannerInput(
                base_plan=plan,
                events=(),
                evidence=(),
                material_transactions=(),
                remaining_stock=plan.stocks,
                patch=candidate,
            )
            simulations.append(
                serial(
                    simulate_patch(
                        inputs,
                        process=context.process,
                        allow_synthetic=True,
                        family_validator=stand_continuation_blockers,
                    )
                )
            )
        return dict(
            proposals=serial(proposals),
            diagnostics=serial(diagnostics),
            simulations=simulations,
        )

    step(
        "repair",
        "Propose and simulate unapproved hypothetical repairs",
        "MetaMuse plus actual simulate_patch",
        {"reported_problem": problem, "physical_history": []},
        repair,
    )
    step(
        "segmentation",
        "Localize cardboard last",
        "SAM 3.1 segment",
        {
            "concept": "cardboard",
            "units": "source image pixels; no physical dimensions",
        },
        lambda: gateway.segment(ImageInput(image, content_type, True), "cardboard"),
    )
    save()
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("explicit --live required")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    image = args.image.read_bytes()
    if not 0 < len(image) <= 5_000_000:
        parser.error("image outside limit")
    content_type = (
        "image/png" if image.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    )
    if content_type == "image/jpeg" and not image.startswith(b"\xff\xd8\xff"):
        parser.error("PNG/JPEG required")
    # Validate prerequisites before any reservation or provider dispatch.
    Project.model_validate(snapshot["artifacts"]["project"])
    DesignContext.model_validate(snapshot["artifacts"]["design_context"])
    BuildPlan.model_validate(snapshot["plan"])
    key = load_key()
    args.output.mkdir(parents=True, exist_ok=False)
    authorization = dict(
        scope="synthetic intake/design/read-only snapshot/compiler/diagnosis/repair/replanner; SAM last",
        allowed_models=["muse-spark-1.3", "sam-3.1"],
        max_calls=8,
        max_input_tokens=64_000,
        max_text_bytes=48_000,
        max_image_bytes=5_000_000,
        max_output_tokens=8192,
        max_response_bytes=2_000_000,
        per_call_timeout_seconds=120,
        automatic_retries=0,
        starts_at=now().isoformat(),
        expires_at=(now() + timedelta(minutes=20)).isoformat(),
        historical_unknowns="preserved; not settled by this run",
    )
    append(args.output / "ledger.jsonl", dict(event="authorization", **authorization))
    transport = ReservedTransport(MetaHTTP(key), args.output, authorization)
    steps = run(snapshot, image, content_type, args.output, transport)
    append(
        args.output / "ledger.jsonl",
        dict(
            event="run_complete",
            provider_calls=transport.calls,
            halted=transport.halted,
            physical_verification="not_attempted",
        ),
    )
    print(
        json.dumps(
            dict(
                provider_calls=transport.calls,
                halted=transport.halted,
                statuses={s["id"]: s["status"] for s in steps},
            )
        )
    )


if __name__ == "__main__":
    main()
