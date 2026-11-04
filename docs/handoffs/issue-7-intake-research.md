# Research in the intake workbench

Draft for [#7](https://github.com/olartgabo/forma/issues/7). @olartgabo owns the
workbench and evaluation. @ResniDev reviews consumption of the provider result.
This draft can be reviewed independently. Implementation consumes the generated
research API contract from the [provider lane](https://github.com/olartgabo/forma/issues/9).

## Builder flow

In initial intake, offer **Find ideas for this build** alongside the existing
path to propose a design. A builder can use it for an unfamiliar goal or when a
first design is blocked. Place the action next to the goal and constraints so
it can also fit the [guided intake work](https://github.com/olartgabo/forma/issues/177)
without depending on photo measurement estimates.

1. Show the exact public search brief made from generic categories the builder
   chooses. Explain that Meta will use it for public web search. Require
   separate consent for this action. Photos and saved private details are
   excluded from that brief.
2. Show honest progress, elapsed waiting and a way to continue with manual
   intake or propose without research. Surface usable partial findings if one
   task fails. Distinguish no sources, unavailable research and an unsupported
   request. Treat a timeout separately from the engine's feasibility decision.
3. Show which approach is worth proposing, which input would change that
   decision, or what blocks it. Keep conflicting sources visible. Separate
   cited claims from the engine's findings and identify essential requirements
   the engine cannot check. Label research references separately from the
   FORMA manual.
4. When the result is eligible, let the builder explicitly use the findings
   with the existing design action.
   Pass only the opaque research ID. Show actual compiler/fabrication blockers
   or measurement requests when the engine cannot produce a plan. Valid
   proposals follow the ordinary preview and approval path.

Discard late responses when the brief, saved goal, inventory revision or project
changes, and clear the selection when consent is withdrawn. Continuing without
research ends local waiting and ignores late results. If a paid request's
outcome is unknown, show that state and leave dispatch reconciliation to the
server. Use existing bilingual request status patterns and generated API types.
Make links and actions keyboard usable at mobile widths and show text for each
status.

## Judge scenario and evaluation

A judge asks for a landscape phone stand with room for a charging plug using
scrap cardboard, tape and no glue. Web references may assume wider sheets, a
different hinge or an unavailable tool. The result should expose those
assumptions and suggest a supported adaptation to examine. FORMA should either
produce a checked proposal, ask for a measurement that can change the result,
or name the constraint that blocks the build. If the engine cannot check plug
clearance, keep it unresolved and let the builder explicitly revise the brief.
For a second run, use confirmed stock too small for every supported candidate
and no purchases. Citations may still appear, and the engine must return a
blocker with zero usable candidates.

Compare the same held-out briefs and confirmed inventories with and without
research, with a search-only run as an end-to-end baseline.
Use an ordinary supported case, a constrained case, an impossible stock case
and an excluded high-risk request. Add a conflict case where a plausible source
recommends a joint the existing checks reject. Use the same model and design
budget for the proposal phase. For each run record source usefulness, unsupported
suggestions, whether the verdict cited the right check, actionable questions
or blockers, candidates accepted by the engine, extra provider requests,
reported usage and elapsed time. Report counts
and denominators for the cases actually run. Keep offline replay, live provider
results, compiler acceptance and physical evidence separate.

To isolate adjudication, freeze the same validated scout findings, analyst
mappings and deterministic check results for paired runs. In the control, use
code to format that evidence for review without an agent recommendation. In
the treatment, add only the adjudicator. Score the suggested action against
the same prewritten expected blocker, measurement or eligible approach.

## Acceptance

- [ ] Browser coverage exercises consent, no research, cited findings, partial
      findings, contradictory findings, no sources, provider outage, stale
      results after a project or inventory change, and continuation without
      research. A late result cannot
      change the design context after the builder opts out.
- [ ] Source links render as safe text and HTTPS links. Findings cannot become
      editable stock facts, steps, geometry or physical evidence. Research never
      bypasses expected revision checks or user approval.
- [ ] A connected regression verifies the ordinary flow and the constrained
      and impossible cases using the real deterministic validation path. Test
      replays use labeled provider fixtures. Record any separate authorized live
      comparison before proposing enablement.

This draft specifies product behavior and evaluation. Implementation and
acceptance runs are pending.
