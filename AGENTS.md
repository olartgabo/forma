# Working in FORMA

Read the complete [formspec.md](formspec.md) before implementation. Then read
[docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md)
and the README of the module being changed. Current user instructions take
precedence. Record deliberate product changes in [docs/decisions.md](docs/decisions.md).

## Ownership and coordination

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
