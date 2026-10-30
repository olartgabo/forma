# Web product

Owner: @olartgabo. Reviewer: @ResniDev. Status: reserved module; no runnable app.
Issues: #1, #7, #11, #12 and #14.

Implement Next.js/React/TypeScript mobile flows: Start, Inventory, Design,
Manual, I'm stuck, Adapt review and Proof. Reserve `src/app`,
`src/components/{inventory,manual,adapt,proof}` and `src/lib/api.ts` when
implementation starts. Tool versions and commands are chosen in #1.

Consume generated domain/API types through the API client. Keep model keys,
provider SDKs, stock validation and revision authority on the server.
Show missing measurement, infeasible, loading, failed and stale-revision states.
Require explicit user approval/physical confirmation and preserve manual fallback.

First handoff: project/intake screen shell with confirmed dimension editing;
later connect authoritative SVG steps and the computed adaptation diff.
See [contracts](../../docs/contracts.md) and [development](../../docs/development.md).
