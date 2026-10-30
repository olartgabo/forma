# API and orchestration

Product/persistence owner: @olartgabo. Gateway/orchestrator owner: @ResniDev.
Each reviews the other's API contract changes. Status: reserved module.
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

First handoffs: health/project scaffold (#1/#6), live provider compatibility
record (#4), and [contracts](../../docs/contracts.md). No install/test command exists yet.
