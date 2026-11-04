"""Publish only labeled synthetic, typed walkthrough results; never runtime stores."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DESCRIPTIONS = {
    "intake-project": (
        "Your starting point",
        "I need a small stand to keep a recipe card upright on my desk. This example uses hypothetical cardboard and tape, with every assumption retained below.",
    ),
    "intake-inventory": (
        "Materials and dimensions",
        "Two synthetic sheets and a tape roll are saved with explicit assumed dimensions. These values are example inputs, not photo measurements.",
    ),
    "measurement-decision": (
        "What needs measuring?",
        "The measurement engine chooses the next useful question from the saved inputs. Read its reasons and missing capabilities below.",
    ),
    "photo-measure": (
        "Try a scaled photo estimate",
        "A separate generated flat-sheet image tests the reference-based measurement engine. Its estimates remain unconfirmed and do not replace this project's stock assumptions.",
    ),
    "synthesis-search": (
        "Find possible designs",
        "The synthesis engine searches the bounded design space against the synthetic stock, profiles and constraints. Candidate and rejection reports are saved.",
    ),
    "synthesis-probe": (
        "Compare another footprint",
        "A second footprint is checked against the same assumptions. Inspect the changed parameters and feasibility report.",
    ),
    "compiler-renderer": (
        "Check the chosen design",
        "The actual compiler validates the example plan, and the renderer generates its geometry, material quantities and instructions.",
    ),
    "manual": (
        "Explore every instruction",
        "The manual has eight generated steps. Use the numbered buttons or Previous and Next instruction to move through the drawings.",
    ),
    "activate": (
        "Review the planned version",
        "The example version is activated only in an isolated synthetic store. Activation records no physical work or test result.",
    ),
    "assembly-view": (
        "Explore the assembled shape",
        "Rotate the actual engine projection and select its parts. This is the planned geometry; it does not establish what a person built.",
    ),
    "stability-connected": (
        "Check stability readiness",
        "The connected saved-plan route asks for measurements. This is a real blocker returned by the runtime, even though the separate hypothetical model can be evaluated.",
    ),
    "stability-save": (
        "Keep the stability reply",
        "The report-saving route retains its actual outcome. Saving a report does not fill missing measurements or establish a physical pass.",
    ),
    "fabrication": (
        "Check tools and material use",
        "The fabrication engine evaluates operation order, stock and tool availability using this example's synthetic context.",
    ),
    "fabrication-assess": (
        "Review the next operation",
        "Explicit sample tool declarations are assessed for this report. They remain synthetic, and the assessment records no completed work.",
    ),
    "stage-0": (
        "Preview the full target",
        "The stage diagnostic evaluates the complete planned geometry with hypothetical properties. Physical progress remains empty.",
    ),
    "stage-flat-panels": (
        "Inspect the flat-panel case",
        "This separate hypothetical case exercises the engine's supported flat-panel stage. Inspect its modeled status and limits.",
    ),
    "repair-search": (
        "Something changed: find a repair",
        "The hypothetical problem is a brace needing replacement. The real search engine evaluates candidates against the saved stock and empty physical history.",
    ),
    "replanner-simulate": (
        "Inspect the blocked replacement",
        "Replacement is blocked because this project has no recorded cut. The reply preserves that dependency rather than inventing completed work.",
    ),
    "replanner-resize": (
        "Compare a feasible revision",
        "A different scenario resizes the unfinished base. The real replanner computes its new plan and manual. This remains an unapproved preview.",
    ),
    "construction": (
        "Try another shape",
        "A separate hypothetical ramp exercises generic construction, piece naming, stage generation and fabrication. It does not replace the recipe-card stand.",
    ),
    "proof": (
        "Final review and Proof",
        "Proof shows the saved plans, coverage and unresolved verification. No physical events, evidence or test passes were created.",
    ),
    "progress": (
        "What is actually complete?",
        "The software walkthrough reaches its final review. The physical build is still not started, and all of its real-world checks remain to be performed.",
    ),
}


def prepare(source, target, provider=None, reference_image=None):
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    target.mkdir(parents=True, exist_ok=True)
    # Keep only public synthetic content; runtime database paths and duplicate
    # internal artifacts are deliberately absent from the downloadable bundle.
    result = {
        key: snapshot[key]
        for key in (
            "schema_version",
            "label",
            "physical_verification",
            "provider_calls",
            "generated_at",
            "project_id",
            "version_id",
            "limitations",
            "steps",
        )
    }
    result["source_head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    steps = result["steps"]
    by_id = {step["id"]: step for step in steps}
    photo = by_id.pop("photo-measure")
    ordered = []
    for step in steps:
        if step["id"] == "photo-measure":
            continue
        ordered.append(step)
        if step["id"] == "measurement-decision":
            ordered.append(photo)
    result["steps"] = ordered
    for step in ordered:
        if step["id"] in DESCRIPTIONS:
            step["title"], step["summary"] = DESCRIPTIONS[step["id"]]
        elif step["id"].startswith("stage-"):
            step["summary"] = (
                "This in-memory hypothetical prefix asks what the stage engine can model after these planned operations. Unsupported stage results remain visible. No physical event is saved."
            )
        # Request success and engine readiness are separate facts.
        if step["status"] == "returned":
            step["status"] = "returned"
    scene = photo["output"]["synthetic_image"]
    shutil.copyfile(source.parent / scene, target / "measurement-reference.png")
    photo["image"] = "/walkthrough/measurement-reference.png"
    photo["output"]["synthetic_image"] = photo["image"]
    if provider:
        live = json.loads(provider.read_text(encoding="utf-8"))
        result["provider_calls"] = live["provider_calls"]
        result["provider_usage"] = live.get("usage")
        result["actual_usage_totals"] = live.get("actual_usage_totals")
        result["limitations"] = [
            item
            for item in result["limitations"]
            if "deliberately excluded" not in item
        ]
        result["limitations"].extend(live.get("limitations", []))
        # The provider companion uses the same scenario, but an AI suggestion
        # cannot retrospectively become the source of a precompiled example.
        result["limitations"].append(
            "The canonical stand and its manual were generated from explicit synthetic parameters. Saved AI proposals are separate unapproved suggestions, not the authorship source of that plan."
        )
        for step in live["steps"]:
            step = dict(step)
            step["output"] = {
                "runtime_reply": step["output"],
                "validated_model_replies": step.get("typed_model_replies", []),
                "tool_diagnostics": step.get("tool_diagnostics"),
            }
            step["id"] = (
                "sam-segmentation"
                if step["id"] == "segmentation"
                else "muse-" + step["id"]
            )
            if step["id"] == "sam-segmentation":
                step["title"] = "Locate cardboard in the photo"
            summaries = {
                "muse-intake": "Muse read the supplied synthetic reference and returned material proposals and questions. Image contents are separate reference imagery; they do not verify the example stock or dimensions.",
                "muse-design": "Muse uses the saved-context tool and proposes designs for compiler review. Read each actual candidate status and blocker below. The canonical example comes from explicit synthetic parameters; it is independent of these proposals.",
                "muse-diagnosis": "Muse separates visible details from hypotheses and questions. The reported concern is hypothetical; no real damage or physical failure is claimed.",
                "muse-repair": "Muse proposes a change for the hypothetical base-depth problem. The actual replanner evaluates it against the canonical stand with empty physical history. Read the simulation status below; every physical check remains pending.",
                "sam-segmentation": "SAM locates cardboard in source-image pixels. Returned boxes are photo annotations and establish no physical dimensions.",
            }
            step["summary"] = summaries.get(
                step["id"], "Saved typed provider reply from the bounded synthetic run."
            )
            before = (
                "intake-inventory"
                if "intake" in step["id"]
                else "compiler-renderer"
                if "design" in step["id"]
                else "repair-search"
                if any(word in step["id"] for word in ("diagnos", "repair"))
                else "photo-measure"
            )
            index = next(
                (i for i, item in enumerate(ordered) if item["id"] == before),
                len(ordered) - 2,
            )
            ordered.insert(index, step)
    if reference_image:
        image = reference_image.read_bytes()
        if (
            not image.startswith(b"\x89PNG\r\n\x1a\n")
            or not 0 < len(image) <= 5_000_000
        ):
            raise ValueError(
                "An explicitly supplied synthetic PNG reference is required"
            )
        (target / "material-reference.png").write_bytes(image)
        for step in ordered:
            if step["id"] in ("muse-intake", "muse-diagnosis", "sam-segmentation"):
                step["image"] = "/walkthrough/material-reference.png"
    result["limitations"].extend(
        [
            "This walkthrough presents recorded results for interaction review. It does not call providers or mutate a real project as you browse.",
            "Local nearby-supplier work and the active live-intake repair branch remain unpublished work in progress and are not represented as deployed features.",
            "Optional image generation and voice are not connected stages in the current product pipeline.",
        ]
    )
    for step in ordered:
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        domain = output.get("status")
        if not domain and isinstance(output.get("report"), dict):
            domain = output["report"].get("status")
        if (
            not domain
            and isinstance(output.get("previews"), list)
            and output["previews"]
        ):
            domain = output["previews"][0].get("simulation", {}).get("status")
        runtime = output.get("runtime_reply")
        if isinstance(runtime, dict):
            candidates = runtime.get("compiler_results") or runtime.get("simulations")
            if candidates and len({c.get("status") for c in candidates}) == 1:
                domain = candidates[0].get("status")
        if domain:
            step["result_status"] = domain
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    for forbidden in ("C:\\Users\\", "Authorization", "Bearer ", "api_key", "dpapi"):
        if forbidden in encoded:
            raise ValueError("Unexpected private runtime field in public walkthrough")
    path = target / "project.json"
    path.write_text(encoded + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "output/pipeline-walkthrough/snapshot.json",
    )
    parser.add_argument(
        "--target", type=Path, default=ROOT / "apps/web/public/walkthrough"
    )
    parser.add_argument("--provider", type=Path)
    parser.add_argument("--synthetic-reference", type=Path)
    args = parser.parse_args()
    print(prepare(args.source, args.target, args.provider, args.synthetic_reference))
