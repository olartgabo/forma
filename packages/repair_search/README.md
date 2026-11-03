# Repair search

Owner: @olartgabo. Reviewer: @ResniDev. Issue: #151. Status: bounded offline
search implemented; physical recovery unverified.

`generate_candidates(plan, target_ids, remaining_stock, resizes)` enumerates
flat `RepairPatch` edits from operators FORMA already supports, in a fixed
order: for each target part, a replacement from every remaining usable sheet or
strip, then a resize to each size the user measured; for each joint on a target
part (or a target joint), every other allowed tested profile. Angle changes
would need an invented angle and are never generated. Patch IDs are hashes of
their content, so the same inputs give the same candidates.

`search_repairs(candidates, *, limits, simulate, schedule, prior_plans)`
simulates at most `limits.max_evaluated` candidates (12 at most) with the
caller's existing `simulate_patch` path, then schedules each feasible revision
with the #150 fabrication report. A candidate is rejected when the simulator
blocks it, when #150 cannot schedule its remaining work, when its plan equals
the base or an ancestor (`cycle`), or when it equals an earlier candidate's
plan (`duplicate`). Rejections keep their exact blockers.

Feasible candidates are ranked by known terms only: the replanner's known
weighted cost, then fewer physical undos, more preserved operations, less
consumed sheet area and connector length, fewer unknown physical checks, and
the patch ID as the final tie-break. Time, purchase price and strength stay
unknown. No stability report covers a repair yet, so coverage is reported as
`unverified`.

Status is `found` when any candidate ranks, `exhausted` when the evaluation
limit stopped the search before every generated candidate was checked, and
`infeasible` when every generated candidate was checked and none passed.

The API stores the top three ranked candidates as ordinary adapt previews, so
approval reuses the atomic `adapt/commit` re-simulation. Searching records no
physical event, receipt or revision. A second repair of an already-repaired part
and other unsupported cases come back as infeasible because the simulator and
family validator block them; this package never adds operators of its own.
