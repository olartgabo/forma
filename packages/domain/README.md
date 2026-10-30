# Domain

Owner: @ResniDev. Consumer/reviewer: @olartgabo. Issue #3.

`forma_domain.models` is the Pydantic source for immutable plan, operation,
execution, evidence, material, proposal and mutation contracts. Installed with
`forma_api` by the root project. No network, storage or provider dependency.

```sh
uv sync --locked
npm run contracts:generate
npm run contracts:check
uv run --locked pytest packages/domain/tests
```

JSON Schema and an OpenAPI 3.1 component catalog live in `generated/`;
TypeScript lives in `apps/web/src/lib/generated/contracts.ts`. The generator
derives all fields from Pydantic and rejects unsupported schema constructs.
Generated files use the generator's deterministic formatting. Never edit them.

`synthetic_inventory_a()` and the generated fixture are synthetic, unconfirmed
software examples. Thickness is unknown. They establish no actual inventory,
tested tolerance, geometry feasibility or physical success.

Read [the exact interface handoff](../../docs/handoffs/issue-3-domain.md) before
implementing consumers. Pydantic checks schema/IDs/order; geometry, conservation,
history resolution, authenticated scope and atomic commits remain consumer duties.
