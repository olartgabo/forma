# Domain

Owner: @ResniDev. Reviewer/consumer: @olartgabo. Issue: #3.
Status: requirements only; Pydantic models have not been implemented.

Define typed measurements/stock/parts/joints, a closed operation union, versioned
plans, append-only material/physical events, checkpoints, evidence and typed
patches. Units, stable IDs, provenance, reversibility and unknown values are explicit.

Depend only on domain-level Python/Pydantic utilities. Generate JSON/OpenAPI and
TypeScript through an agreed reproducible command; consumers do not duplicate
models by hand. Exact package/import names and generated locations are pending.

First deliverable: runtime-validatable contracts, synthetic inventory A fixture,
schema generation and bad-ID/unit/operation tests. Label synthetic values;
measured inventory comes from #2. See [contracts](../../docs/contracts.md).
