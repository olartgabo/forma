# Issue #9 bounded proposals handoff

Owner: @ResniDev. Reviewer: @olartgabo. Offline implementation; no live or physical
success claimed. Stacked on domain #3 and gateway #4. No state-writing endpoint,
database integration, manual replacement or user approval is introduced.

## Consumer interface

`forma_api.proposal_service.ProposalService(gateway, validator).run(task, snapshot,
user_text, image=..., photo_evidence_id=...)` handles `intake`, `design`, `diagnose`
and `repair`. Result status is `proposed`, `blocked`, `needs_clarification` or
`stopped`. Only compiler-accepted candidates enter a usable proposal. Every
rejected candidate retains its exact typed `Blocker` code/message/target IDs in
`reviews`; feedback is replayed unchanged if another bounded attempt is possible.
Timeouts/round exhaustion stop and ask for measurement/photo clarification.

Flat product outputs reuse `DesignProposals`, `DiagnosisProposal`, `RepairProposals`
from `forma_domain.models`. Intake has observation labels/questions only and
literal `measurement_source=unknown`; it cannot return inventory/measurement
records. No competing Stock/BuildPlan schema or generated contract is added.

`ProposalSnapshot` is an immutable, revalidated service input: project/version,
remaining stock, profile catalog, constraints, optional current plan, chronological
events, evidence and current operation. Size/count bounds reject oversized
context before provider access. Scope and references validate before calls.
Diagnosis requires a scoped user photo plus consented image bytes and current
step. Exact byte-to-asset authorization remains the authenticated caller's job.
No key is necessary for offline checks.

`HistoricalScope` maps an authorized historical version to its bounded part,
operation and checkpoint IDs. Historical events/evidence validate against that
specific version and remain in chronological context even when old parts/cuts
no longer appear in the active plan. Current records cannot borrow historical
IDs. The caller must load these IDs from authorized immutable history; the model
never supplies a resolver or changes history. Diagnoses can name those historical
IDs; repair patches remain restricted to current targets.

## Compiler/replanner injection

The injected synchronous validator takes `(DesignCandidate | RepairPatch,
ProposalSnapshot)` and returns a runtime-valid `CompilerResult`, private service
`CandidateFeedback(status, blockers)`, or repair-only `SimulationResult`.
A missing validator stops design/repair
before calling a provider. Arbitrary return shapes or callback exceptions stop
with `compiler_failed`; exception strings never enter traces. Accepted compiler
plans must retain the project scope. The service returns proposals and computed
repair previews, never activates a callback plan or interprets compiler acceptance
as physical success.

#5 supplies `forma_compiler.validate_plan`. The supported #8 template adapter
constructs `CompilerInput` plus measured `StandParameters`, then calls
`forma_renderer.compile_stand(request, parameters, process=...)`; no generic
`compile_candidate` function is implemented. #10 supplies repair simulation/preservation.
The adapter does not invent kerf, tolerances, process evidence or measurements
to make that callback available. Callbacks must be fast, read-only and
deterministic; Python callbacks are not forcibly preempted, but an expired job
rejects their output and never makes a further model call.

`forma_api.compiler_adapter.build_validator(...)` now supplies this callback.
Bind authorized `process`, `stand_parameters`, `profile_evidence`, `base_plan`,
`events`, `evidence`, `material_transactions`, `historical_plans` and explicit
`allow_synthetic` at construction. Design also requires a trusted `created_at`;
the snapshot has no timestamp and the adapter never reads a clock to invent one.
Cut geometry uses the supplied process's recorded minimum kerf and edge margin.
Missing trusted inputs return distinct `needs_measurement` feedback.

Design candidates run through `compile_stand`. Repair patches run through
`simulate_patch` with `stand_continuation_blockers`; exact blockers are preserved.
Repair scope, exact base plan, profiles and history must agree with the bound
server state. Profile evidence must agree with history and pass the same
provenance checks as rendering. Synthetic profile evidence requires explicit
opt-in even when the cutting process is otherwise verified. Design parameters
and creation time do not gate repairs, which use the bound plan's geometry.

The factory is available for callers; no authenticated route is added here.

For repairs the adapter returns the original `SimulationResult`. Accepted repair
feedback without that typed result is rejected with `compiler_failed`. The
service strictly revalidates patch/base identity and the new plan's project,
parent and version scope. `ProposalOutcome.repair_results` contains one feasible
result per accepted patch, ordered by `rank_feasible`; proposal candidates have
the same order. Results come from the accepting callback invocation and are
never re-simulated by the service. Blocked candidates remain in reviews only.
Partial cost terms stay partial, with unmeasured estimates null.

Repair diffs are outside `SafeProposalTrace` and outside feedback replay. This
is an API-local outcome field; exposing it through OpenAPI or web requires a
separate consumer contract handoff. No generated contract changes are implied.

Repair target mapping: resize/replace part -> current part ID; replace profile ->
current joint ID; change angle -> current version ID. Replacement stock/profile
must already exist in the trusted snapshot; profile IDs must be allowed by
constraints. Purchases and alternate stock requests remain questions, never
automatically available inventory. Unknown or duplicate references reject before
compiler execution; stale bases return exact `stale_version` blockers.

## Bounded provider and tools

`model_gateway.ProposalBudget` shares one absolute deadline and model-call counter
across feedback retries. Default four provider turns includes tool-call requests
and final structured-output requests; associated validated deterministic tool
execution occurs inside those turns, so the common path costs two turns.
There are at most two design or three repair candidates **across the request**,
not per retry. No hidden retry replenishes budgets. Existing #4 callers remain
compatible without passing a shared budget.

Typed read-only tools: `get_project_snapshot(project_id, version_id)` and
`get_supported_joint_profiles(project_id, version_id, profile_ids)`. Tool extras,
wrong scope, unknown IDs and unauthorized tool names stop. The profile catalog
includes explicit experimental/tested status; a name does not promote a profile.
No tool exists for plan activation, completed work, test passes, stock creation
or manual replacement. Local deterministic validation follows every candidate.

Trusted packaged prompts at `bounded-proposals-v1` stay in the system role.
User text/snapshot/feedback are serialized JSON data in the user role. Prompt
separation reduces injection risk but does not establish truth: validation and
capability boundaries enforce authority. Trace schema `domain-proposals-v1`
records task/version/round/tool counts, latency, reported token usage and safe
error codes; labels, questions, evidence, IDs, photos and exception details are
excluded. Exact blockers appear only in the user-facing result and model feedback.
No live usage/cost or physical evidence exists.

## Verification and remaining work

Offline tests cover hostile tool scope/args, invented resource IDs, stale patches,
over-limit proposals and retries, exact compiler feedback, callbacks/errors,
timeouts and exhausted rounds, diagnosis separation, photo scope, old consumed
operations, no immutable input/manual mutation and safe traces. Run:

```sh
uv run --locked pytest apps/api/tests/test_proposal_service.py
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m forma_domain.generate --check
```

Checks actually run: proposal-service tests 40 passed; full offline suite 89 passed; Ruff check passed; Ruff format --check reported 52 files formatted; generated contracts current; git diff --check clean. Python 3.12.6, Pydantic 2.14.2, pytest 9.2.0, Ruff 0.17.3. No root package/lock
or generated files changed. Those counts describe the original service slice.
The #40 adapter adds real compiler/replanner service integration tests; current
checks are recorded in its PR. Authenticated #6 routes remain follow-up work.
Live Meta key/account/region/privacy/quota and consented team-photo
blockers from #4 still apply. No fixture pass establishes G0/G2/G3.
