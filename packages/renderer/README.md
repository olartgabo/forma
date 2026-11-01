# SVG renderer and stand template

Owner: @ResniDev. Consumer/reviewer: @olartgabo. Issue #8.

`forma_renderer.compile_stand(CompilerInput, StandParameters, *, process,
allow_synthetic=False) -> CompilerResult` produces one narrow three-panel
triangular stand with a folded retaining lip and three tape hinges. Base depth,
lip, device contact measurements, tape overlap, tool/access confirmations and
physical-test conditions are explicit inputs. Support angle and dimensions come
from CompilerInput; brace length follows the triangle geometry. The independent
compiler validates the resulting plan before it can be rendered.

`render_manual(plan, *, process, profile_evidence=(), allow_synthetic=False)`
returns a frozen Manual with eight core SVG Panels plus replacement cuts, bill of materials,
blockers and `physical_verification="not_attempted"`. It revalidates the plan and
its exact supported topology/operation sequence before rendering. Unsupported or
incomplete inputs yield blockers and no panels. No provider, HTTP or persistence.

`stand_continuation_blockers(plan)` is the pure family validator for replanner
callbacks. It shares the manual's geometry, active-role topology, operation and
checkpoint checks. A cut, unjoined panel may be replaced with an equivalent panel
from measured remaining stock. Retired parts and cuts remain in the plan and BOM;
assembly views use active parts and feature IDs. Supplemental cuts have separate
headings while the eight core step slots stay stable, preserving unchanged panels.
All hashes still cover the complete visible SVG. The replanner supports extending
the original uncut base depth with regenerated brace/layout; other stand resize
variants remain blocked. No physical verification is implied.

The default path requires actual user-confirmed cutting evidence and resolved
user-observed tested tape/fold profiles; unknown dimensions block work. Synthetic
fixtures require explicit opt-in on both calls and label every panel. Neither
schema validation nor rendering establishes physical feasibility or a pass.

SVG panels contain stock-frame cut allocation, numbered parts and dimensions,
fold symbols, labelled joints/arrows, tools, manual checkpoints and expected
state IDs. Display dimensions use two decimals; underlying plan dimensions stay
unchanged. The whole source region is consumed in this first layout; unallocated
area (including kerf/margins) is explicitly waste, never reusable offcut stock.

Identical visible inputs produce identical SVG/hash. Version IDs and timestamps
are excluded; changed geometry alters affected panels. Cache reuse says nothing
about checkpoint freshness. API callers must maintain version association.

```sh
uv sync --locked
uv run --locked pytest packages/renderer/tests
npm run check
```

See [the handoff](../../docs/handoffs/issue-8-stand-manual.md). Measured inventory,
real profile experiments and a physical build are still required before calling
any parameterization tested or buildable.
