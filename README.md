# FORMA

Turn what you have into what you need.

FORMA helps a person turn measured reused materials into a small tabletop
fixture, follow a deterministic assembly manual, and recover when the physical
build disagrees with the plan.

**Status: workspace and domain contracts.** Next.js serves a workbench preview and FastAPI
serves a health endpoint. Projects, model connections, measured inventories and
physical results are not implemented yet.
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
.github/                Contribution templates and offline CI
```

Each module has a README describing its boundary, owner and next deliverable.
Only the web preview and API health route are implemented. Other module paths
reserve the boundaries described in the spec.

## Run and verify

Install Node **22.21.0**, npm **11.16.0** and uv **0.11.16**. Python **3.12.6**
is pinned in `.python-version`; uv can install it. From the repository root:

```sh
uv python install
npm ci
uv sync --locked
```

Start these in two terminals, both at the repository root:

```sh
npm run dev:api
```

```sh
npm run dev:web
```

Open <http://127.0.0.1:3000> for the preview. The API at
<http://127.0.0.1:8000/api/health> returns `{"status":"ok"}`; interactive
OpenAPI documentation is at <http://127.0.0.1:8000/docs>. Health reports process
liveness only. Stop each server with Ctrl+C in its terminal.

No `.env` or model key is needed. `.env.example` reserves a server-only key for
future gateway work; the current apps do not read it. Never put credentials in
`NEXT_PUBLIC_*` variables or commit private physical photos.

```sh
npm run check
```

This runs the same checks as `.github/workflows/checks.yml`: Prettier/Ruff
formatting, Ruff lint, Next route generation plus strict TypeScript checking,
offline Python tests, and a production web build. Individual scripts are
`format:check`, `lint`, `typecheck`, `test`, and `build`; `npm run format` applies
formatting. Prettier covers JS/TS/CSS/JSON/YAML source and configuration; Ruff
covers Python. Generated files and lockfiles are excluded from formatting.
The supplied `formspec.md` remains byte-for-byte unchanged.

`pytest` excludes tests marked `live` by default. Future provider tests must be
marked and explicitly selected with `uv run --locked pytest -m live`. A fixture
or health pass does not establish model compatibility or physical feasibility.
For a production preview, run `npm run build` then `npm run start -w @forma/web`.

Dependency updates use `npm install` and `uv add`; commit the generated
`package-lock.json` and `uv.lock`, never edit them by hand. Schema generation
and shared domain contracts remain assigned to #3. See the
[#1 handoff](docs/handoffs/issue-1-workspace.md) for the proposed integration
boundary and pending review.

## First acceptance gate

By the spec's October 31 target, demonstrate one real functioning build and one
non-hardcoded, compiler-approved repair with preserved work, material accounting
and repeated checks. All gates are currently **unverified**. See the
[evaluation protocol](docs/evaluation-protocol.md) and
[submission checklist](docs/submission.md).

Domain runtime contracts are implemented in `forma_domain.models`. Run
`npm run contracts:generate` and `npm run contracts:check`. See the
[issue #3 handoff](docs/handoffs/issue-3-domain.md) for exact consumer interfaces.
