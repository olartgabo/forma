# FORMA

Turn what you have into what you need.

FORMA helps a person turn measured reused materials into a small tabletop
fixture, follow a deterministic assembly manual, and recover when the physical
build disagrees with the plan.

**Status: documentation scaffold.** Application code, package manifests, model
connections, measured inventories and physical results are not implemented yet.
The original [formspec.md](formspec.md) is preserved as the product source of truth.

## Start here

1. Read [formspec.md](formspec.md), [AGENTS.md](AGENTS.md) and the
   [architecture](docs/architecture.md).
2. Check the [work allocation](docs/development.md) and
   [pending decisions](docs/decisions.md).
3. Pick an issue from the [execution tracker](https://github.com/olartgabo/forma/issues/17).
   Create a branch, keep the change within its acceptance criteria and update
   the relevant handoff document before requesting review.

| Owner      | Work                                   | First issues                                                                                                                      |
| ---------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| @ResniDev  | Physical compiler and Meta integration | [#3 contracts](https://github.com/olartgabo/forma/issues/3), [#4 live model spike](https://github.com/olartgabo/forma/issues/4)   |
| @olartgabo | Product and physical validation        | [#1 workspace](https://github.com/olartgabo/forma/issues/1), [#2 measured materials](https://github.com/olartgabo/forma/issues/2) |

This named ownership supersedes the original spec's A/B ownership mapping.
Both engineers participate in the physical build and recovery.

## Repository map

```text
apps/web/               Product UI: Next.js, React, TypeScript
apps/api/               FastAPI routes, persistence, Meta gateway, orchestration
packages/domain/        Pydantic models and exported schema source
packages/compiler/      Pure stock, geometry, joint and operation validation
packages/replanner/     Repair feasibility, preservation, undo and invalidation
packages/renderer/      Authoritative deterministic SVG manual
packages/eval/          Offline cases, baseline comparison and result summaries
fixtures/               Synthetic cases and consented measured inventory data
data/physical-tests/    Redacted physical observations and evidence manifests
docs/                   Architecture, contracts, decisions and experiment guides
prompts/                Versioned model task instructions and tool boundaries
scripts/                Future schema export, smoke test and evaluation commands
.github/                Contribution templates and future CI
```

Each module has a README describing its boundary, owner and next deliverable.
These are reserved implementation locations; no imports or runnable services
are claimed by this tree.

## Run and verify

There is no application install, dev, typecheck or test command yet. Issue #1
must introduce pinned tooling, real commands and matching CI. Do not copy
MCPJam Inspector workspace commands into this repository.

For this documentation scaffold, inspect the tree with `git diff --check` and
verify local Markdown links before publishing. Read
[development.md](docs/development.md) for the implementation verification bar.

## First acceptance gate

By the spec's October 31 target, demonstrate one real functioning build and one
non-hardcoded, compiler-approved repair with preserved work, material accounting
and repeated checks. All gates are currently **unverified**. See the
[evaluation protocol](docs/evaluation-protocol.md) and
[submission checklist](docs/submission.md).
