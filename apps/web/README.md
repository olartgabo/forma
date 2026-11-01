# Web product

Owner: @olartgabo. Reviewer: @ResniDev. Status: local intake workbench.
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
The page uses local system fonts and needs no model key. Creating or reopening
projects, saving inventory and uploading photos require the private API.

Enter an existing development owner credential in the workbench. It stays in
React memory, is cleared on disconnect/refresh and is never written to browser
storage. The project ID can remain in the URL for reopening after reconnecting.
The web server proxies `/api` to loopback port 8000 by default, forwarding only
the caller's credential. Set `FORMA_API_ORIGIN` in the web process environment
before dev/build to choose another fixed origin. Hosted login remains pending.

The workbench creates/reopens projects, uploads and links private photos, and
edits one physical stock item per row. Empty dimensions stay unknown; entered
measurements have explicit confirmation. Saving retains the inventory revision
and uses retry keys; stale saves require reloading and reviewing the inventory.
The inventory form also saves available tools, a device description, confirmed
device mass/viewing angle/footprint limits and willingness to get more material.
Blank measurements stay unknown; editing a value or its source clears confirmation.
Requirements and stock share one revision and retry payload. Photos do not produce
measurements or physical evidence. Segmentation boxes,
live proposals and assembly/revision/proof screens remain
pending. See the [intake handoff](../../docs/handoffs/issue-7-intake.md).
The [requirements handoff](../../docs/handoffs/issue-7-requirements.md) documents
the persisted planning inputs and consumer boundary.

`npm run test:web` runs the native Node client tests without a browser or model
key. Root `npm run check` includes those tests, API/domain contract freshness,
formatting, Python tests, TypeScript and production build. Client request/response
types come from the API Pydantic exporter; do not hand-edit generated files.

Later connect authoritative SVG steps and the computed adaptation diff.
See [contracts](../../docs/contracts.md) and [development](../../docs/development.md).
