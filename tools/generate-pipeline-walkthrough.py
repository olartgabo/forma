"""Run current engines on isolated SYNTHETIC data, without provider calls.

No physical reports are submitted. Diagnostic completion prefixes exist only in
memory. The retained SQLite database contains plans/previews, never physical passes.
"""

# The repository's existing synthetic helpers require these search paths before
# their imports. They are explicitly software fixtures, never physical evidence.
# ruff: noqa: E402

import argparse
import json
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
sys.path.insert(0, str(ROOT / "packages/photo_measure/tests"))

from fastapi.testclient import TestClient
from forma_stability.lab_plan import inspect_plan
from test_plans import AUTH, TOKENS, approval, stand_inputs

from forma_api import adapt, fabrication_runtime, synthesis_runtime
from forma_api.design_context import DesignContext, StaticDesignContextResolver
from forma_api.main import create_app
from forma_api.plans import CompilePreview, PlanService
from forma_api.projects import ProjectStore

LABEL = "Recipe-card stand — synthetic UX walkthrough"
NOTICE = "SYNTHETIC assumptions only; no physical work or test was performed."


def serial(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def generate(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    # Never reopen an old synthetic run and silently append/replay its records.
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory = destination / "runs" / run_id
    directory.mkdir(parents=True)
    data_dir = directory / "data"
    steps = []

    def record(step_id, title, engine, inputs, function):
        entry = dict(id=step_id, title=title, engine=engine, input=serial(inputs))
        try:
            result = function()
            if hasattr(result, "status_code"):
                entry["http_status"] = result.status_code
                output = result.json()
                entry["status"] = "returned" if result.is_success else "blocked"
            else:
                output = serial(result)
                entry["status"] = "returned"
            entry["output"] = output
        except Exception as error:
            entry.update(
                status="error",
                error=dict(type=type(error).__name__, message=str(error)),
            )
            output = None
        steps.append(entry)
        return output

    holder = {}

    def resolver():
        return StaticDesignContextResolver(holder.get("context"))

    with ExitStack() as scope:
        # Process-local fixture switches are restored on exit; no server settings
        # or guard files are changed, and no real deployment is contacted.
        for module in (adapt, fabrication_runtime, synthesis_runtime):
            scope.enter_context(patch.object(module, "ALLOW_SYNTHETIC", True))
        scope.enter_context(
            patch.object(synthesis_runtime, "default_context_resolver", resolver)
        )
        # Fail closed if this offline walkthrough ever reaches a provider transport.
        scope.enter_context(
            patch(
                "http.client.HTTPSConnection.request",
                side_effect=RuntimeError(
                    "Provider/network calls forbidden in synthetic walkthrough"
                ),
            )
        )
        client = scope.enter_context(TestClient(create_app(data_dir, TOKENS)))

        def request(method, suffix, body=None):
            kwargs = dict(headers=AUTH)
            if body is not None:
                kwargs["json"] = body
            return client.request(method, "/api/projects" + suffix, **kwargs)

        create = {
            "goal": LABEL + ". Hold a recipe card on a desk. " + NOTICE,
            "idempotency_key": "walkthrough-create",
        }
        project = record(
            "intake-project",
            "Start a synthetic recipe-card project",
            "project persistence",
            create,
            lambda: request("POST", "", create),
        )["project"]
        pid = project["id"]
        stocks, constraints, candidate, parameters, process, profiles = stand_inputs(
            pid
        )
        parameters = parameters.model_copy(
            update={
                "device_label": "SYNTHETIC recipe-card holder load",
                "test_surface": "SYNTHETIC kitchen desk",
            }
        )
        spare = stocks[0].model_copy(
            update={
                "id": "synthetic-spare",
                "usable_regions": (
                    stocks[0]
                    .usable_regions[0]
                    .model_copy(update={"id": "synthetic-spare-region"}),
                ),
            }
        )
        stocks = (*stocks, spare)
        inventory = dict(
            expected_revision_id=project["revision_id"],
            idempotency_key="walkthrough-inventory",
            stocks=serial(stocks),
            user_confirmed=True,
            requirements=dict(
                tools=["ruler", "scissors"],
                device_description="Hypothetical recipe-card holder; all numerical loads are synthetic",
                constraints=serial(constraints),
            ),
        )
        project = record(
            "intake-inventory",
            "Save labeled synthetic sheet, spare and tape",
            "inventory persistence",
            inventory,
            lambda: request("PUT", f"/{pid}/inventory", inventory),
        )["project"]
        context = dict(
            parameters=parameters,
            process=process,
            joint_profiles=profiles,
            kerf_mm=2,
            edge_margin_mm=4,
        )
        holder["context"] = DesignContext(
            project_id=pid, inventory_revision_id=project["revision_id"], **context
        )
        identity = dict(
            expected_inventory_revision_id=project["revision_id"],
            expected_active_version_id=None,
            expected_last_event_id=None,
        )
        record(
            "measurement-decision",
            "Ask which measurement matters next",
            "forma_measurement",
            identity,
            lambda: request(
                "POST",
                f"/{pid}/measurement-decisions",
                {k: v for k, v in identity.items() if k != "expected_last_event_id"},
            ),
        )
        search = record(
            "synthesis-search",
            "Search real stock-feasible designs",
            "forma_synthesizer",
            identity,
            lambda: request("POST", f"/{pid}/synthesis/search", identity),
        )
        if search and search.get("candidates"):
            chosen = search["candidates"][0]
            domain = next(
                d for d in search["domains"] if d["parameter"] == "footprint_depth_mm"
            )
            probe = identity | dict(
                search_id=search["search_id"],
                design=chosen["design"],
                parameter="footprint_depth_mm",
                value_mm=domain["lower_mm"],
            )
            record(
                "synthesis-probe",
                "Inspect another footprint",
                "forma_synthesizer",
                probe,
                lambda: request("POST", f"/{pid}/synthesis/probe", probe),
            )
        body = CompilePreview(
            expected_revision_id=project["revision_id"],
            idempotency_key="walkthrough-compile",
            candidate=candidate,
        )
        service = PlanService(ProjectStore(data_dir), allow_synthetic=True)
        compiled = record(
            "compiler-renderer",
            "Compile and render the stand manual",
            "forma_compiler + forma_renderer",
            dict(request=body, context=context),
            lambda: service.compile_preview("alice", pid, body, **context),
        )
        if not compiled or not compiled.get("version"):
            raise RuntimeError(
                "Synthetic plan did not compile; inspect recorded engine result"
            )
        version = compiled["version"]
        vid = version["version_id"]
        plan = version["plan"]
        record(
            "manual",
            "Read every generated manual panel",
            "forma_renderer",
            {"version_id": vid},
            lambda: request("GET", f"/{pid}/manual/{vid}"),
        )
        activation = approval(project)
        project = record(
            "activate",
            "Activate the planned version without recording work",
            "plan persistence",
            activation,
            lambda: request("POST", f"/{pid}/plans/{vid}/activate", activation),
        )["project"]
        active_identity = dict(
            plan_version_id=vid,
            expected_inventory_revision_id=project["revision_id"],
            expected_last_event_id=None,
        )
        record(
            "assembly-view",
            "Project the planned assembly for the viewer",
            "forma_assembly_view + canonical geometry",
            active_identity,
            lambda: request(
                "GET",
                f"/{pid}/assembly-view?plan_version_id={vid}&expected_inventory_revision_id={project['revision_id']}&expected_last_event_id=",
            ),
        )
        record(
            "stability-connected",
            "Check saved-plan stability readiness",
            "forma_stability API adapter",
            active_identity,
            lambda: request("POST", f"/{pid}/stability/analyses", active_identity),
        )
        record(
            "stability-save",
            "Retain a stability report when inputs permit",
            "stability report persistence",
            active_identity,
            lambda: request(
                "POST",
                f"/{pid}/stability/reports",
                active_identity | {"idempotency_key": "walkthrough-stability"},
            ),
        )
        record(
            "fabrication",
            "Check operation tools, stock and dependencies",
            "forma_fabrication",
            {"version_id": vid},
            lambda: request("GET", f"/{pid}/versions/{vid}/fabrication"),
        )
        assessment = dict(
            expected_inventory_revision_id=project["revision_id"],
            expected_last_event_id=None,
            additional_tools=["ruler", "scissors"],
            tools_confirmed=True,
        )
        record(
            "fabrication-assess",
            "Assess explicitly declared synthetic tools",
            "forma_fabrication",
            assessment,
            lambda: request(
                "POST", f"/{pid}/versions/{vid}/fabrication/assess", assessment
            ),
        )
        # These in-memory diagnostic prefixes exclude functional-test passes.
        loads = dict(
            part_mass_g={p["id"]: 20 for p in plan["parts"]},
            device_mass_g=180,
            device_x_mm=40,
            device_y_mm=70,
            device_z_mm=100,
            required_margin_mm=2,
            tolerance_mm=0.1,
            gravity_m_s2=9.81,
            uniform_mass_assumed=True,
            connector_shares_included=True,
            full_base_contact_assumed=True,
            rigid_device_attachment_assumed=True,
        )
        for prefix in range(len(plan["operations"]) + 1):
            experiment = dict(plan=plan, completed_prefix=prefix, loads=loads)
            record(
                f"stage-{prefix}",
                "Planned target"
                if prefix == 0
                else f"Hypothetical prefix {prefix}: {plan['operations'][prefix - 1]['id']}",
                "canonical geometry + forma_stability",
                experiment,
                lambda experiment=experiment: inspect_plan(experiment),
            )
        flat = dict(plan=plan, completed_prefix=1, stage_example=True)
        record(
            "stage-flat-panels",
            "Evaluate separately supported flat panels",
            "forma_stability.stage",
            flat,
            lambda: inspect_plan(flat),
        )
        repair = dict(
            expected_version_id=vid,
            expected_last_event_id=None,
            idempotency_key="walkthrough-repair-search",
            target_ids=["stand-brace"],
            connector_measurements=[],
            remaining_confirmed=True,
        )
        record(
            "repair-search",
            "Search a hypothetical brace replacement",
            "forma_repair_search + forma_replanner",
            repair,
            lambda: request("POST", f"/{pid}/repairs/search", repair),
        )
        repair_patch = dict(
            id="walkthrough-replace-brace",
            base_version_id=vid,
            kind="replace_part",
            target_id="stand-brace",
            replacement_stock_id="synthetic-spare",
            replacement_profile_id=None,
            width_mm=None,
            height_mm=None,
            angle_deg=None,
            rationale=NOTICE,
        )
        simulation = dict(
            expected_version_id=vid,
            expected_last_event_id=None,
            idempotency_key="walkthrough-simulate",
            candidates=[repair_patch],
            connector_measurements=[],
            remaining_confirmed=True,
        )
        record(
            "replanner-simulate",
            "Simulate replacement without committing a revision",
            "forma_replanner",
            simulation,
            lambda: request("POST", f"/{pid}/adapt/simulate", simulation),
        )
        resize = simulation | dict(
            idempotency_key="walkthrough-resize",
            candidates=[
                repair_patch
                | dict(
                    id="walkthrough-resize-base",
                    kind="resize_part",
                    target_id="stand-base",
                    replacement_stock_id=None,
                    width_mm=80,
                    height_mm=160,
                )
            ],
        )
        record(
            "replanner-resize",
            "Try resizing the unfinished base",
            "forma_replanner",
            resize,
            lambda: request("POST", f"/{pid}/adapt/simulate", resize),
        )
        from forma_stability.lab_construction import run_generation

        construction_input = dict(
            shape=dict(kind="ramp", width_mm=80, depth_mm=140, height_mm=150),
            synthetic_fabrication=True,
        )
        record(
            "construction",
            "Generate a separate hypothetical ramp's construction graph",
            "forma_stability.construction + forma_fabrication",
            construction_input,
            lambda: run_generation(construction_input),
        )
        record(
            "proof",
            "Read saved Proof with no physical reports",
            "Proof snapshot persistence",
            {"project_id": pid},
            lambda: request("GET", f"/{pid}/proof"),
        )
        record(
            "progress",
            "Verify no physical work was recorded",
            "progress persistence",
            {"version_id": vid},
            lambda: request("GET", f"/{pid}/versions/{vid}/progress"),
        )

        def photo_measurement():
            import cv2
            from forma_photo_measure import estimate
            from scenes import (
                MATERIAL,
                box_around,
                camera,
                make_input,
                rect_mm,
                render,
                texture,
            )

            outline = rect_mm(200, 60, 280, 190)
            tex = texture([(outline, (), MATERIAL)])
            k, h = camera(tilt_deg=20, yaw_deg=8)
            image = render(tex, h, k=k)
            cv2.imwrite(str(directory / "synthetic-photo.png"), image)
            inputs = make_input(image, box_around(h, outline))
            return dict(
                input=serial(inputs),
                result=serial(estimate(image, inputs)),
                synthetic_image="runs/" + run_id + "/synthetic-photo.png",
            )

        record(
            "photo-measure",
            "Estimate a synthetic flat sheet against a printed reference",
            "forma_photo_measure",
            {"scene": "Synthetic 280 × 190 mm sheet; no real-photo accuracy claim"},
            photo_measurement,
        )

    result = dict(
        schema_version=1,
        label=LABEL,
        notice=NOTICE,
        physical_verification="not_attempted",
        provider_calls=0,
        generated_at=datetime.now(UTC).isoformat(),
        project_id=pid,
        version_id=vid,
        steps=steps,
        plan=plan,
        manual=version["manual"],
        artifacts={
            "database": str(data_dir / "projects.sqlite3"),
            "plan": plan,
            "manual": version["manual"],
            "design_context": serial(holder["context"]),
            "project": project,
        },
        limitations=[
            "All dimensions, loads, profile/process evidence and inventory are labeled synthetic assumptions.",
            "Hypothetical operation prefixes are in-memory diagnostics; no physical events or test passes are saved.",
            "Actual connected runtime responses may be blocked or unsupported; a returned response is not a pass.",
            "Muse/SAM provider actions are deliberately excluded from this deterministic snapshot.",
            "The flat-sheet photo scenario is separate from the stand stock and supplies no confirmed inventory measurements.",
        ],
    )
    target = destination / "snapshot.json"
    target.write_text(
        json.dumps(serial(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target, result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/pipeline-walkthrough"
    )
    args = parser.parse_args()
    target, result = generate(args.output.resolve())
    print(
        json.dumps(
            dict(
                snapshot=str(target),
                steps=len(result["steps"]),
                errors=[s["id"] for s in result["steps"] if s["status"] == "error"],
                provider_calls=0,
                physical_verification="not_attempted",
            )
        )
    )
