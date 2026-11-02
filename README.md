# FORMA

Turn what you have into what you need.

FORMA helps a person turn measured reused materials into a small tabletop
fixture, follow a deterministic assembly manual, and recover when the physical
build disagrees with the plan.

**Status: intake, saved manuals and user-reported progress.** Next.js supports goal intake,
private photos and confirmed inventory editing through the scoped FastAPI API.
The compiler, renderer, replanner and proposal service are implemented. Saved
plan previews, explicit initial approval and immutable manual viewing are connected;
physical confirmations, evidence links and material receipts are persisted. A
Proof snapshot and photo-excluded text/JSON exports expose recorded claims.
Consented Muse intake, design generation and read-only diagnosis are connected;
offline stand repair simulation covers panel replacement, base resize and
attached-brace tape undo. Repair activation, hosted identity and physical
results remain pending.
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
The local intake workbench, private project/inventory/photo API and offline compiler, renderer,
replanner and provider proposal services are implemented. Live-provider and
physical gates remain unverified.

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

No model key is needed for offline checks. Private project routes require explicit
server credentials; see [API setup](apps/api/README.md). Export environment values
before starting the API (`.env.example` documents them; it is not loaded automatically).
Never put credentials in
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

## Local intake

Start both `npm run dev:api` and `npm run dev:web` from separate terminals.
Configure `FORMA_API_TOKENS` in the API process environment as described in the
[API README](apps/api/README.md). There is no default owner credential. Enter
your configured development access key in the workbench; it stays in memory and
must be entered again after refresh. Save the project ID to reopen the project.

The web server proxies `/api` to `http://127.0.0.1:8000` by default. If needed,
set server-only `FORMA_API_ORIGIN` before starting or building the web app. It
must be an HTTP(S) origin without a path or credentials. No server owner token
is inserted into requests. Hosted sign-in remains pending; this is local
development access.

Add one inventory row per physical item. Leave unknown dimensions blank and
explicitly confirm measurements you took. Private photos can be uploaded and
linked to stock; they are not sent to a model or used to infer dimensions.
The same form saves available tools, a device description, confirmed device mass,
viewing angle and footprint limits. Requirements and materials share one revision;
blank measurements remain unknown. Saving inventory does not generate instructions
or authorize cutting. See the
[intake handoff](docs/handoffs/issue-7-intake.md) for scope and remaining work.

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

Domain runtime contracts are implemented in `forma_domain.models`. API-local
Pydantic records also generate browser request/response types. Run
`npm run contracts:generate` and `npm run contracts:check` for both exporters. See the
[issue #3 handoff](docs/handoffs/issue-3-domain.md) for exact consumer interfaces.
