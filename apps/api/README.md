# API and orchestration

Product/persistence owner: @olartgabo. Gateway/orchestrator owner: @ResniDev.
Each reviews the other's API contract changes. Status: health scaffold.
Issues: #1, #4, #6, #9 and #12.

Implement FastAPI with project-scoped routes and Pydantic validation. Reserve
`src/forma_api/routes`, `services`, `models`, `providers` and `tests` as code
lands. Keep shared domain entities in [packages/domain](../../packages/domain/README.md).

| Boundary                                                           | Owner                     | Deliverable                                                               |
| ------------------------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------- |
| Routes, sessions, project service, private uploads and persistence | @olartgabo                | Authenticated/idempotent API and durable plan/event/evidence records      |
| Providers/model_gateway and bounded orchestration                  | @ResniDev                 | Validated proposals and safe traces; no autonomous physical state commits |
| Revision transaction                                               | @olartgabo with @ResniDev | Atomic user approval against validated expected-version proposal          |

Provider tasks cannot rewrite completed events or record test passes. Apply
project auth before data access, validate uploads, keep secrets private and
bound external calls. Use storage adapters; offline compiler modules never
import API services. Coordinate changes to shared routes/models in a handoff.

## Run and check

From the root, `uv sync --locked` installs the editable `forma_api` package from
`apps/api/src/forma_api` using the root `pyproject.toml`. `npm run dev:api` starts Uvicorn
at `127.0.0.1:8000`; `GET /api/health` reports process liveness and `/docs`
exposes FastAPI's OpenAPI UI. No database or provider readiness is implied.

`npm test` runs the offline pytest suite. `npm run lint` and
`uv run --locked ruff format --check .` check Python source. No model key is
needed. See the [root README](../../README.md) for pinned tools and setup.

Only the health route is implemented. Project routes, authentication, persistence,
uploads and provider integration remain #6/#4. The
[#1 handoff](../../docs/handoffs/issue-1-workspace.md) reserves the service/domain
boundary for review before those changes.
