# Issue 152 assembly viewer

The active manual offers a read-only nominal assembly view. The versioned API
adapter calls the existing `preview_geometry` / `project_nominal_geometry`
producer and returns its exact facets, IDs, SI coordinates, stage and hash.
`packages/assembly_view/projection.ts` owns only orthographic display projection.
No SVG parsing, physical pose producer, GPU context, render loop or model call
was added. Product decision D059 records the bounded scope.

The authenticated GET binds the active project, plan, inventory revision and
required explicit history cursor in one database transaction. Empty query cursor
means an empty history. Foreign plans return 404; stale snapshots return 409.
The evidence revision hashes the stored evidence, invalidations and current
typed measurement batch. Geometry response validators and the browser reject
foreign/stale identities before displaying a scene. Requests use no-store.

Planned and user-reported assembled stages remain separately labeled nominal
geometry. Partial, failed, damaged, carried, detached and repaired physical states
outside the canonical producer's support show no final geometry and retain the
SVG/manual/history fallback. Display controls cannot record physical work.
Missing report overlays are explicitly unavailable, without blocking viewing.
The viewer now consumes the merged saved-report store through a bounded read of
the latest 50 project/plan reports. A saved overlay must match current typed
measurement evidence, profiles, project, plan, inventory, history, canonical hash,
producer and engine/dependency versions. Each displayed orientation must match
its stored case, with a completed tipping calculation. A newer measurement or
stale/mismatched report leaves ordinary nominal viewing available.

The saved center of mass, support polygon and critical edge use the same camera
projection as the canonical facets. Selecting a saved case, orbiting, zooming and
separating parts performs no reads, writes or analysis. Separation hides the
world-space overlay until its display offset returns to zero. Labels distinguish
modeled point estimates from physical verification.

Orbit and tilt work through buttons or focused arrow keys; pointer drag orbits
and native range controls provide zoom/separation. Parts have exact ID labels,
front-layer callouts and large selection buttons. Part-to-operation buttons
select the existing manual step using stable IDs and honor its pending-operation
navigation lock. Display separation shifts only projected source parts; folded
facets sharing a part receive the same offset. Reduced motion uses immediate
updates with no animation. Closing, refreshing, switching project/context or
disconnecting clears the scene and aborts outstanding reads. Canonical facet and
operation counts remain bounded by the generated domain contracts.

Dedicated validation commands:

```sh
uv run --locked pytest apps/api/tests/test_assembly_view.py -q
node --experimental-strip-types --test packages/assembly_view/tests/projection.test.mjs apps/web/tests/assembly-view.test.mjs
uv run --locked python apps/web/tests/assembly-view-fixture.py <outside-repo-fixture.json>
node apps/web/tests/assembly-view.browser.mjs <playwright-module> http://127.0.0.1:3039 <outside-repo-fixture.json>
```

The fixture exporter runs actual synthetic compiler/renderer/API inputs to
produce planned, unsupported partial and user-reported assembled responses.
The intercepted local-browser runner checks 390px and 1280px, exact facet counts,
keyboard/pointer controls, native vertical touch tilt on mobile, zoom/separation,
stable manual links, no display-driven analysis requests or writes,
unsupported/unavailable/stale/foreign response cleanup and a delayed response
after disconnect. A separate explicit measurement capture uses real exported
API responses: the editor locks part-to-manual navigation, and saving refreshes
the open viewer with the new history cursor and evidence revision without a
manual refresh. That path allows one explicit read-only stability analysis and
one intercepted synthetic measurement save. All other mutations and non-local
traffic are blocked. Screenshots are saved to the operating
system temporary directory as `forma-assembly152-390.png` and `-1280.png`.

The current saved-overlay follow-up adds exact-identity, producer/dependency,
case-orientation and stale-measurement checks, plus a database read-only assertion
with numerical analysis patched to fail if called. Its browser check selects a
second saved case, verifies camera projection and hidden overlays during
separation, and records screenshots as `forma-assembly-overlay-current-390.png`
and `-1280.png` in the operating system temporary directory.

Local targeted results: Python 22 passed; Node 8 passed; browser PASS at both
widths. Generated contracts, repository-wide checks and independent review are recorded by the
integrating owner on the final combined head. These are software observations,
not provider, hosted or physical-build acceptance.

Independent review repairs set `touch-action: none` on the drawing so native
vertical drag reaches its tilt handler; the surrounding page remains scrollable.
The connected mount includes the measurement-save revision in its viewer refresh
key. The browser regression covers both repaired behaviors and the existing
navigation lock during measurement entry.
