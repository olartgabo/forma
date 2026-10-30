# Issue #5 offline validation handoff

Branch: issue/5-offline-compiler. Base: issue/3-domain-contracts (PR #20), itself
stacked on workspace PR #18. Issue #5 remains open for measured profile integration
and the other engineer's review; no physical acceptance is claimed.

## Interface and behavior

`from forma_compiler import CutProcess, validate_plan`.
`validate_plan(plan: BuildPlan, *, process: CutProcess | None = None,
allow_synthetic: bool = False) -> CompilerResult` is pure resource/operation validation.
It replays allocations and connectors; checks source ownership, usable condition,
nonoverlap, kerf/margins/orientation, part/feature production, profile fit, dependency
ancestry, joint effects, detach inverse/loss and measurement prerequisites. Schema
validation rejects invalid references and nonpreceding/cyclic dependencies first.
Unknown critical stock measurements and unconfirmed tools/access yield blockers.

The validator retains plan status and never activates plans, completes operations,
returns consumed stock, or certifies physical function. Unrepresented residual sheet
area is waste, not reusable offcut. Real salvage must be represented as new reviewed
remaining-stock regions with immutable physical/ledger provenance by the service;
this module cannot create inventory from a proposed salvage claim.

CutProcess and JointProfile are trusted server catalogue inputs, never untrusted
model/public API overrides. Process evidence is scoped to the project; profile IDs
must resolve to reviewed bench evidence at the stand compilation boundary (#8).
Full device/angle/contact/footprint template constraints belong to #8. Renderer and
replanner consume these checks but must separately preserve physical event history.

## Validation

Initial and review regression suite: 40 tests pass across API/domain/compiler,
including 20 compiler tests. Independent review identified missing feature/measurement
and joint producer dependencies, incomplete slot/fold compatibility, detach semantics
and process evidence scope; fixes and regressions are included. Full workspace check
result will be recorded before publication.

## External facts

No measured stock A/B, actual kerf/margin, joint tolerance or physical bench outcome
exists in the supplied intake. Synthetic fixtures are opt-in only and cannot promote
real profiles. Physical testing and real catalogue population remain #2/#13 inputs.

Full npm run check passed: Prettier, Ruff49files/lint, generated freshness, strict TypeScript,40tests and production build. Two additional regression checks then passed with42totaltests. No source implementation changed after the full workspace check.
