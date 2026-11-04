# Assembly display

`projection.ts` projects existing canonical SI facets onto an orthographic display.
Orbit, zoom and separation are presentation controls only. The canonical source
object and its identity remain unchanged. No SVG parsing, physical pose solver,
analysis request, animation loop or GPU context is used.

The scoped API adapter lives in `forma_api.assembly_view_runtime`; the connected
React consumer lives in `apps/web/src/components/assembly-view`. Unsupported
physical stages retain the SVG manual and history. Missing report overlays remain
explicitly unavailable and never block ordinary nominal viewing. Current exact
saved-report overlays share the canonical facet camera through `projectWorldPoints`.
World-space overlays receive no separated-part offset and are hidden while parts
are separated. Camera/case controls never recalculate the report.

Run `node --experimental-strip-types --test packages/assembly_view/tests/projection.test.mjs`
and `uv run --locked pytest apps/api/tests/test_assembly_view.py` from the root.
These are software checks, never physical evidence.
