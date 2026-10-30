# Web product

Owner: @olartgabo. Reviewer: @ResniDev. Status: runnable workbench preview.
Issues: #1, #7, #11, #12 and #14.

Implement Next.js/React/TypeScript mobile flows: Start, Inventory, Design,
Manual, I'm stuck, Adapt review and Proof. Reserve `src/app`,
`src/components/{inventory,manual,adapt,proof}` and `src/lib/api.ts` when
implementation starts. Tool versions and commands are chosen in #1.

Consume generated domain/API types through the API client. Keep model keys,
provider SDKs, stock validation and revision authority on the server.
Show missing measurement, infeasible, loading, failed and stale-revision states.
Require explicit user approval/physical confirmation and preserve manual fallback.

## Run and check

After the root setup, `npm run dev:web` serves the preview at
`http://127.0.0.1:3000`. `npm run typecheck -w @forma/web` generates Next route
types and runs strict TypeScript checks. `npm run build -w @forma/web` builds
the production app, then `npm run start -w @forma/web` serves it locally.
The page uses local system fonts and needs no model key or API connection.

Project creation, inventory forms and assembly screens remain pending. The
preview states this explicitly. It does not hold synthetic progress or dimensions.

First product handoff: project/intake screen with confirmed dimension editing;
later connect authoritative SVG steps and the computed adaptation diff.
See [contracts](../../docs/contracts.md) and [development](../../docs/development.md).
