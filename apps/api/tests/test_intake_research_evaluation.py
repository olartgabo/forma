"""Paired API evaluation with synthetic provider replies.

Run with pytest -s to print the per-brief observations and the aggregate scores.
The timings measure local API wall time with an in-process transport.
"""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from statistics import median
from time import perf_counter

from test_intake_research import body, revise_inventory
from test_intake_research import ready as ready
from test_intake_research import setup as setup
from test_intake_research_muse import citation, message, response, search_call
from test_synthesis_routes import identity, post, state

from forma_api import intake_research as runtime

MODES = ("stock-only", "citations-only", "full-adjudication")
ROLES = ("scout", "analyst", "adjudicator")


@dataclass(frozen=True)
class Brief:
    name: str
    use_case: str
    useful_direction: str | None = None
    supporting_citation: int | None = None
    stop_reason: str | None = None


# Human labels read the fixture claims and the brief. A recommendation must
# point to both the correct measured depth direction and the supporting claim.
BRIEFS = (
    Brief("compact-phone", "phone_stand", "min", 1),
    Brief("brace-space-reading", "reading_stand", "max", 0),
    Brief("conflicting-precedents", "reading_stand"),
    Brief("no-citations", "phone_stand"),
    Brief("irrelevant-citation", "phone_stand"),
    Brief("essential-plug-clearance", "phone_stand", stop_reason="unsupported"),
    Brief("insufficient-sheet", "reading_stand", stop_reason="blocked"),
    Brief("unconfirmed-device-mass", "phone_stand", stop_reason="needs_input"),
)

# Fixed transcripts, independent of the scorer and any option ordering in the
# request. The irrelevant citation probes a plausible but ungrounded pick.
TAPE_HINGE = "The two cardboard panels in this example are joined with tape."
COMPACT = (
    "The tabletop phone stand examples favor a shallower "
    "base to leave more room for a keyboard on the same desk."
)
BRACE_SPACE = (
    "In these tabletop reading stands, the example with a deeper base leaves "
    "more room to position the rear brace."
)
NOTEBOOK_SPACE = (
    "Other reading stand examples favor a shallower base to leave room for a notebook."
)
CLAIMS = {
    "compact-phone": (TAPE_HINGE, COMPACT),
    "brace-space-reading": (BRACE_SPACE, TAPE_HINGE),
    "conflicting-precedents": (BRACE_SPACE, NOTEBOOK_SPACE),
    "no-citations": (),
    "irrelevant-citation": (TAPE_HINGE,),
}
SELECTIONS = {
    "compact-phone": ("option-a", "shallower_base", 1),
    "brace-space-reading": ("option-b", "deeper_base", 0),
    "conflicting-precedents": ("no_preference", None, None),
    "irrelevant-citation": ("option-b", "deeper_base", 0),
}


class ReplayTransport:
    def __init__(self, brief):
        self.brief = brief
        self.calls = Counter()

    def post(self, path, payload, timeout):
        assert path == "/responses" and 0 < timeout <= runtime.DEADLINE_SECONDS
        if "tools" in payload:
            self.calls["scout"] += 1
            assert payload["input"] == runtime.BRIEFS[self.brief.use_case]
            findings = [
                message(
                    claim,
                    (
                        citation(
                            end_index=len(claim),
                            title=f"Synthetic example {index + 1}",
                            url=f"https://example.org/fixture/{index + 1}",
                        ),
                    ),
                )
                for index, claim in enumerate(CLAIMS[self.brief.name])
            ]
            return response(search_call(), *(findings or [message(TAPE_HINGE)]))

        role = payload["text"]["format"]["name"]
        if role == "ResearchAnalysis":
            self.calls["analyst"] += 1
            return response(message('{"focus":"joint_profiles"}'))
        assert role == "ResearchSelection"
        self.calls["adjudicator"] += 1
        option, tradeoff, source = SELECTIONS[self.brief.name]
        return response(
            message(
                json.dumps(
                    {
                        "option_id": option,
                        "tradeoff": tradeoff,
                        "source_index": source,
                    }
                )
            )
        )


def assess(brief, mode, result, calls, elapsed):
    stock_only = mode == "stock-only"
    search = result if stock_only else result.get("search")
    candidates = search["candidates"] if search is not None else []
    recommendation = result.get("recommended_candidate_id")
    decision = result.get("decision", result.get("status"))
    useful = False
    correct_abstention = False
    if recommendation is not None and brief.useful_direction is not None:
        depths = {
            candidate["candidate_id"]: candidate["design"]["footprint_depth_mm"]
            for candidate in candidates
        }
        preferred_depth = {"min": min, "max": max}[brief.useful_direction](
            depths.values()
        )
        expected_claim = {"min": "has a shallower base.", "max": "has a deeper base."}[
            brief.useful_direction
        ]
        useful = (
            len(set(depths.values())) > 1
            and depths[recommendation] == preferred_depth
            and result["reason"].endswith(expected_claim)
            and result["recommendation_source_index"] == brief.supporting_citation
        )
    elif recommendation is None and brief.useful_direction is None:
        correct_abstention = brief.stop_reason is None or (
            not candidates
            and (
                decision == brief.stop_reason
                or (brief.stop_reason == "blocked" and decision == "infeasible")
            )
        )

    return {
        "brief": brief.name,
        "mode": mode,
        "decision": decision,
        "coverage": result.get("coverage"),
        "question": result.get("question"),
        "candidates": len(candidates),
        "findings": len(result.get("findings", [])),
        "recommendation": recommendation is not None,
        "useful_recommendation": useful,
        "correct_abstention": correct_abstention,
        "local_api_ms": round(elapsed * 1000, 2),
        "local_research_ms": result.get("provider_elapsed_ms"),
        "requests": {role: calls[role] for role in ROLES},
    }


def test_paired_intake_research_evaluation(ready, monkeypatch):
    client, project, directory, holder = ready
    monkeypatch.setenv("FORMA_INTAKE_RESEARCH", "1")
    rows = []
    ready_stocks = project["stocks"]
    for index, brief in enumerate(BRIEFS):
        if brief.stop_reason == "blocked":
            stocks = deepcopy(ready_stocks)
            sheet = stocks[0]
            sheet["width_mm"]["value"] = 40
            sheet["usable_regions"][0]["geometry"]["width"] = 40
            project = revise_inventory(
                client, project, "eval-tiny-sheet", stocks=stocks
            )
        if brief.stop_reason == "needs_input":
            requirements = deepcopy(project["requirements"])
            requirements["constraints"]["device_mass_g"] = {
                "value": None,
                "unit": "g",
                "source": "unknown",
                "confirmed": False,
            }
            project = revise_inventory(
                client,
                project | {"requirements": requirements},
                "eval-unknown-mass",
                stocks=ready_stocks,
            )
        if brief.stop_reason in ("blocked", "needs_input"):
            holder["context"] = holder["context"].model_copy(
                update={"inventory_revision_id": project["revision_id"]}
            )

        before = state(directory)
        results = {}
        # Rotate which arm runs first to spread warmup effects.
        for mode in MODES[index % len(MODES) :] + MODES[: index % len(MODES)]:
            transport = ReplayTransport(brief)
            with monkeypatch.context() as patch:
                patch.setattr(
                    runtime.MetaGateway,
                    "from_env",
                    lambda: runtime.MetaGateway(transport),
                )
                if mode == "citations-only":
                    # There is no citations-only endpoint. Omit the advisory
                    # analysis for this arm so only the real scout can dispatch.
                    patch.setattr(runtime.muse, "analyze", lambda *_: None)
                path, payload = (
                    ("search", identity(project))
                    if mode == "stock-only"
                    else (
                        "research",
                        body(
                            project,
                            use_case=brief.use_case,
                            needs_plug_clearance=brief.stop_reason == "unsupported",
                            idempotency_key=f"eval-{brief.name}-{mode}",
                        ),
                    )
                )
                started = perf_counter()
                reply = post(client, project, path, payload)
                elapsed = perf_counter() - started
            assert reply.status_code == 200, reply.text
            result = results[mode] = reply.json()
            expected_calls = Counter()
            if mode != "stock-only" and brief.stop_reason is None:
                expected_calls["scout"] = 1
                if mode == "full-adjudication":
                    expected_calls["analyst"] = 1
                    expected_calls["adjudicator"] = bool(CLAIMS[brief.name])
            assert transport.calls == expected_calls
            row = assess(brief, mode, result, transport.calls, elapsed)
            # Score the adversarial reply without requiring the API to accept it.
            if mode == "full-adjudication" and brief.name != "irrelevant-citation":
                assert row["useful_recommendation"] or row["correct_abstention"], row
            if mode == "full-adjudication" and brief.name == "compact-phone":
                wrong_claim = result | {
                    "reason": "Research favored the checked option that uses less tape."
                }
                assert not assess(brief, mode, wrong_claim, transport.calls, elapsed)[
                    "useful_recommendation"
                ]
            rows.append(row)
            print(json.dumps(row))

            after = state(directory)
            prior_receipts = before["requests"]
            receipts = after["requests"]
            assert after | {"requests": prior_receipts} == before
            if expected_calls:
                assert receipts[:-1] == prior_receipts
                assert receipts[-1][:3] == (
                    "alice",
                    f"{project['id']}:intake-research",
                    payload["idempotency_key"],
                )
            else:
                assert receipts == prior_receipts
            before = after

        stock, citations, full = (results[mode] for mode in MODES)
        assert citations["search"] == full["search"]
        assert citations["findings"] == full["findings"]
        assert citations["question"] == full["question"]
        if brief.stop_reason is None:
            assert full["search"] == stock
            assert [finding["claim"] for finding in full["findings"]] == list(
                CLAIMS[brief.name]
            )
        else:
            assert full["decision"] == brief.stop_reason
            assert full["search"] is None
            if brief.stop_reason == "needs_input":
                assert "mass" in full["question"].lower()
    for mode in MODES:
        arm = [row for row in rows if row["mode"] == mode]
        eligible = [row for row in arm if row["brief"] in CLAIMS]
        recommendation_cases = sum(
            brief.useful_direction is not None for brief in BRIEFS
        )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "briefs": len(arm),
                    "useful_recommendations": sum(
                        row["useful_recommendation"] for row in arm
                    ),
                    "recommendation_cases": recommendation_cases,
                    "correct_abstentions": sum(
                        row["correct_abstention"] for row in arm
                    ),
                    "abstention_cases": len(arm) - recommendation_cases,
                    "unsupported_or_unhelpful_recommendations": sum(
                        row["recommendation"] and not row["useful_recommendation"]
                        for row in arm
                    ),
                    "median_local_api_ms": round(
                        median(row["local_api_ms"] for row in eligible), 2
                    ),
                    "latency_cases": len(eligible),
                    "requests": {
                        role: sum(row["requests"][role] for row in arm)
                        for role in ROLES
                    },
                }
            )
        )
