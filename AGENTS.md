# Working in FORMA

Read the complete [formspec.md](formspec.md) before implementation. Then read
[docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md)
and the README of the module being changed. Current user instructions take
precedence. Record deliberate product changes in [docs/decisions.md](docs/decisions.md).

## Ownership and coordination

### November 3, 2026: material-bound proposals and piece references

The user requests construction proposals using actual inventory, broader shapes,
and consistent classified/named pieces across steps and diagrams. MetaMuse may
propose geometry, names and roles; the engine validates identities, constraints
and proposed operations. It does not replace model reasoning or establish visual
or physical observations. Reuse Gabo's fabrication authority and trusted saved
inventory/context. Local imported material records are explicitly unverified;
missing process/profile evidence cannot be replaced with lab fixtures. Fresh
construction proposals must not bypass history-aware repair of an active build.

### November 3, 2026: automatic construction proposals

The user requests automatic construction-step generation for different target
shapes and compatibility with Gabo's fabrication engine. Generate proposed
placement/connection states from the finished target graph; do not require manual
stage authoring or implement another fabrication readiness authority. Real
BuildPlan operation proposals must pass the existing compiler/fabrication report.
Unsupported manufacturing shapes and missing real material/process evidence stay
explicit. Synthetic lab stock is opt-in and cannot become approved physical work.

### November 3, 2026: combined latest work and generic engine diagnostic

The user requests integrating Gabo's latest published work and a friendlier,
step-based diagnostic supporting user-authored shapes, not only the stand preset.
The integration branch combines #154/#156/#158 with #157, preserving each lane's
modules and review gates. This authorizes necessary shared-file merge resolution;
it does not authorize merging unfinished remote PRs or claiming physical success.
Declarative panel geometry and explicit physical stages belong to the engine.
They are not a second fabrication scheduler or proof that arbitrary designs can
be manufactured. Keep example data editable and hypothetical.

### November 3, 2026: explicit engine expansion

The user requests 360-degree rotation in the direct engine diagnostic, supported
intermediate-stage physics, sliding, joint strength and deformation checks.
This authorizes this bounded engine expansion despite the older offline-only
pause. Diagnostic camera controls remain separate from physical transforms.
Gabo retains fabrication rules, repair search and the product viewer; do not
edit the active #154 fabrication implementation. Unknown physical properties
remain unknown, and simplified constitutive checks must name their applicability.

### November 3, 2026: current sequenced workstreams

Issue #17 is the current assignment index. ResniDev owns #146 → #153 → #147 → #148 →
#149 (measured stability, physical stage mechanics, reports/tools, synthesis, active measurement). Gabo owns
#150 → #151, then #152 (fabrication, repair search, viewer). The old #139–#144
issues are superseded historical specifications. PR #145 is the existing shared
geometry/mechanics baseline, not completion of #146. Each owner delivers a full
connected feature; shared registration/migration/mount edits remain serialized.
The user explicitly requested a pure-engine test interface alongside #146;
its labeled hypothetical examples must never become saved physical evidence.
Issue #153 extends physical poses and stage mechanics, not Gabo's executable
operation scheduler or interactive product viewer. The compiled-plan diagnostic
exposes current unsupported stages; it does not complete that extension.

### November 3, 2026: engine completion takes priority

The user explicitly directed that #142 must not remain incomplete because work
was left for Gabo. Implement the canonical geometry and integration dependencies
needed to complete the stability engine in this lane, documenting their shared
interfaces for reuse by #141/#144. This supersedes the earlier requirement to
wait for that owner's producer or agreement. Check for active overlapping work
and keep one canonical implementation, rather than parallel geometry authorities.
Existing review, exact-head checks, physical-evidence gates and provider controls
still apply. This is implementation authorization, not a physical-test claim.

- @ResniDev owns domain, compiler, replanner, renderer, model gateway and prompts.
- @olartgabo owns web, project/persistence API, physical validation, proof and evaluation.
- Shared API files require a contract handoff before either lane changes them.
  The other engineer reviews compiler-affecting changes.
- Use subagents for independent exploration or review across modules. Give each
  writing agent disjoint files. Coordinate contract changes before dependent edits.
  Development agents do not imply additional runtime agents in the product.
- Work on an issue branch. Keep pull requests small and link their acceptance
  criteria. Avoid editing another engineer's active files without coordination.

## Boundaries that must hold

- Pydantic is the domain schema source. Generate API/TypeScript contracts;
  do not maintain handwritten competing schemas or hand-edit generated output.
- Compiler, replanner and renderer run offline on typed inputs. They have no
  model-provider, HTTP, database or UI dependencies.
- Separate immutable plans, chronological physical events and evidence. A new
  version never erases what the builder actually did.
- Unknown measurements stay unknown. Required dimensions and user confirmation
  gate irreversible work. Never invent tolerances, stock, prices or test results.
- Model output is untrusted proposal data. Validate tools and patches; models
  cannot commit plans, complete operations or mark physical tests passed.
- Cap designs at two, repair candidates at three and model/tool rounds at four
  by default. Stop with blockers or targeted questions when candidates fail.
- Cuts consume stock. Preservation requires compatible physical work; undo,
  waste, salvage and dependent rechecks must be explicit.
- User-approved revisions commit atomically with expected-version checks and
  idempotency. Stale writes return 409; rejected proposals leave active state unchanged.
- SVG geometry is authoritative. Illustrative imagery cannot change dimensions,
  part identities or connections. Optional images/voice/3D wait for physical P0.

## Engineering and evidence

Introduce executable checks with implementation. Run the actual affected checks
and report their output; do not claim a documentation scaffold passes app tests.
Offline checks need no model key. Keep live provider tests separately marked.

Review the diff before pushing, including authentication/project scope, upload
validation, secret redaction, stale writes, resource cleanup, schema validation
and false-green tests. Never hand-edit lockfiles or generated/build output.
Use the repository formatter once issue #1 installs it.

Keep secrets, private uploads and raw provider responses out of git. Never send
messages to teammates unless the user explicitly asks; publishing authorized
issues and repository changes is handled through the normal work request.

Write plainly. No dead code, unused abstractions, swallowed errors or invented
success claims. Separate fixture validation, physical attempts and actual
physical passes. Use [docs/agent-workflow.md](docs/agent-workflow.md) for handoffs.

## Native development and connected-demo priority

Current authorization (November 2, 2026) supersedes older Muse-first instructions.
Native ChatGPT/Codex Sol or Terra and terminal Claude Code with explicit Sonnet
selection may implement, test and repair bounded assigned scopes. Claude uses the
existing subscription login, with no new API-key billing or Fable/Haiku fallback.
If rate-limited, checkpoint and let native Codex continue.

Meta/Muse/OpenCode coding workers and Meta-backed coding compaction stay disabled.
Preserve both external STOPs and keep FORMA-Claude-Handoff disabled. MetaMuse is
only the app runtime brain and a provider for bounded live runtime/end-to-end tests.
Native coding, offline checks and read-only Proof verification need no Meta guard
settings or META_GUARD_HOME. Missing live prerequisites block only actual live calls.
Never create dummy settings, copy another user's secrets, remove STOPs or renew
verification windows. Preserve journals, unknown-outcome halting, server-only keys
and payments. The external live verification window is currently expired.

Prioritize connected photo/intake, diagnosis, visible failures and runtime
integration. Offline-engine extensions, synthetic fixture expansion and offline-only
cleanup remain paused. Keep real measurement, confirmation and physical evidence
gates; offline success cannot establish a physical pass.

Use bounded task packets and disjoint owned scopes. After two unsuccessful repair
attempts, obtain one targeted diagnosis; stop with a checkpoint if the subsequent
repair stays blocked. Require a fresh independent Sol/Terra review of the green
diff and passing appropriate local checks before authorized push/publication.
Before merge, all required remote checks must pass on the exact reviewed published
head. Do not
duplicate judges. Native review subagents use fork_turns="none" with only the
bounded packet. Keep native automatic compaction enabled; claim compaction only
with a runtime event. See [current policy](tools/devloop/guarded/POLICY.md) and
[portable handoff](docs/handoffs/issue-16-native-agent-workflow.md).
