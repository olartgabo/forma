# Explicit stage mechanics and material checks

Issue #153 builds on #146, with the user's November 3 request for rotation,
intermediate physics, sliding, joint strength and deformation. Gabo retains
fabrication/execution, repair search and the product viewer. This packet edits
the direct diagnostic and physical engine, not those product modules.

## Physical stage inputs

`forma_stability.stage.evaluate_stage(plan, snapshot, policy)` consumes the
generated `StageSnapshot` contract. Completion IDs must form a dependency-closed
chronological sequence. Actual operation effects determine present parts and
active joints. A snapshot supplies exactly the present source parts, explicit
facet transforms, source mass/COM and contact polygons. Unknown values remain
unresolved. Transforms must be finite, right-handed and orthonormal. Facet poses
preserve the source fold edge; before folding its facets must remain coplanar.
Contacts must lie on the supplied transformed source surfaces, and active joint
edges must coincide. Source mass is counted once, including a folded source.

Active joints determine components. Each component gets its own support hull and
report; disconnected pieces cannot stabilize each other. Rigid-body and active
joint rigidity are explicit assumptions. The support frame is transformed with
gravity; nonhorizontal or noncoplanar support stays unsupported. Camera transforms
never enter this model or its identity. Frame-transformation tests check the
same physical COM, margin and restoring moment under a coordinate change.

The supplied policy is a component template: check types and tolerances apply to
each component, case IDs are derived per component, and the evaluation budget is
shared. The response includes each resulting policy and report, with no combined
assembly pass that could hide an unsupported component.

The lab's **separated flat-parts example** is an explicit invented placement after
cutting (prefix 1 or 2), not a placement inferred from the cutting layout. It
produces three actual component calculations. Other stages require their own
explicit physical snapshot; the final assembly cannot substitute for them.
Functional tests never become physical passes through a diagnostic selection.

## Bounded additional checks

All values are explicit SI `QuantityEstimate`s. Unknowns need measurement;
intervals remain indeterminate. These are conditional scalar models, not material
calibration, conservative uncertainty bounds or general structural certification.

| Check | Calculation | Required scope and limits |
| --- | --- | --- |
| Sliding | static friction capacity = coefficient × supplied compressive reaction | Named active planar interface, supplied tangential demand and coefficient. Reaction distribution is not solved. A nonzero or unknown tangential load blocks the gravity-only tipping claim. |
| Joint capacity | supplied scalar demand versus supplied allowable | Active stage joint, named capacity basis and matching mode. Only submitted modes are checked; no automatic internal-force, peel, moment, fatigue or interaction analysis. |
| Deformation | end-loaded cantilever: PL³/(3EI); centrally loaded simply supported beam: PL³/(48EI) | Named prismatic linear-elastic small-deflection beam, explicit stiffness, span, load and allowable. No buckling, shear deformation, creep, material failure or cardboard anisotropy inferred. |

The beam implementation rejects calculated deflection at least 10% of span as
outside its model-validity guard. That threshold is not a safe-load criterion.
Policy tolerances are numerical; physical reserves and allowable values remain
caller supplied. Equality within tolerance is indeterminate, not a pass.

Formula references: [OpenStax static friction](https://openstax.org/books/college-physics-2e/pages/5-1-friction)
and [MIT 2.080J beam solutions, Lecture 8](https://ocw.mit.edu/courses/2-080j-structural-mechanics-fall-2013/2d0cc95bd3556fdadc28226acabafa51_MIT2_080JF13_Lecture8.pdf).

## Connected boundary

`POST /api/projects/{id}/stability/stage-analyses` accepts the current plan,
expected inventory/history, typed snapshot and policy. Owner authentication and
active-plan checks precede evaluation. Snapshot completion IDs must equal reported
work, and its identity must match project/version/inventory/history. Changed
history returns 409. Damaged, failed or invalidated states require reconciliation
and remain blocked by this adapter.

This endpoint currently accepts **hypothetical** poses/material values only. It
does not persist new measurements or accept claimed observed/confirmed evidence.
Whole-stand measured capture from #146 remains a separate supported flow. Typed
stage observation capture and calibrated material evidence remain unfinished;
do not mark all #153 acceptance complete from this packet. The diagnostic can
explore hypothetical prefixes without writing construction or evidence events.

The direct lab supports drag/touch/keyboard orbit, zoom/reset and fixed views.
These controls alter only the camera. Downloaded experiments preserve original
plan, stage input, policy and report; CLI replay recalculates from the request.

## Verification

Run `uv run --locked pytest packages/stability/tests apps/api/tests/test_stability_stages.py`
and the repository check. API tests use a real activated software plan and reported
cut, evaluate three separate components with the real evaluator, verify no database
writes, and reject stale/foreign/forged-observation inputs. Tests and examples use
synthetic inputs; no provider call or actual physical observation is implied.
