# User-authored assemblies and combined work

The November 3 user request asks for Gabo's latest work and a model-first,
step-based engine diagnostic that accepts new shapes rather than only a stand.

## Combined sources

The integration branch includes the fetched published heads of Gabo's work:

- #154 fabrication: `3ee98127875dc1f9a0c8d0b5f1a19d0ad63643e6`.
- #156 repair search: `548284022e60e2c323b3a7018c7a13feaba57bab`, including #154.
- #158 attached-base recovery: `0b5a783c9c52df36fb9e234510f0cd533e0c8cb4`.

Local integration merges `386bb95` and `cdef62f` combine those with engine PR #157.
They do not merge the original PRs on GitHub. Shared registrations, storage,
generated API types, progress refresh, test scripts and package paths retain
both lanes. Decision numbering from the incoming PRs is reconciled to D041–D043
with corresponding handoff references. The API image now also copies stability
sources, required by its package registration. Docker execution is not available
in this Windows environment; local tests are not a container-runtime claim.

## Use the primary editor

Start `uv run --locked python -m forma_stability --lab --port 3031`.

1. Choose **New assembly**, name a panel and enter its mass if known.
2. Use rectangle dimensions or enter polygon corners in millimetres. This is
   editable geometry, not a selection restricted to sample templates.
3. Set the panel's position and rotation for the current step. Review uniform
   sheet mass, full-face contact and rigidity assumptions explicitly.
4. Add panels and copy the current state into a new stage, then change that
   stage's poses. Connect matching edges when a physical joint is intended.
5. Evaluate the selected stage. Inspect every separate component result. Future
   panels are listed as excluded; they contribute neither mass nor support.
6. Rotate/zoom the model without recalculating. Export the exact calculated
   request and your draft to reproduce a result or retain unfinished edits.

Advanced compiled-stand diagnostics and the material-check examples remain in
the collapsed section. Camera rotation never changes physical geometry. Draft
edits require evaluation before they can support a new numerical result.

## Generic physical boundary

`GenericAssemblyRequest` supplies declarative parts, polygon facets, source seams,
edge-referenced joints, physical stage membership and an explicit `StageSnapshot`.
`evaluate_assembly` validates this data without stand-specific part IDs or fixed
four-corner assumptions. It supports simple planar polygons, including concave
panels, and rejects nonplanar, self-intersecting or degenerate facets.

Multiple facets of one source must have connected declared seams. Physical seam
and joint edges must coincide after transformation. Entire contact polygons must
lie on the transformed source surface, including across concave boundaries.
Mass is counted once per source; disconnected components get separate hulls and
reports. Incomplete poses cannot activate unverified contacts. Hypothetical
uniform-centroid and full-face-contact options are explicit server-side derivations,
not independent browser geometry or inferred observations.

Both the original stand adapter and the generic producer use the shared component
solver and numerical evaluator. Examples for triangle, concave panel, ramp and box
are data, not conditional branches in the geometry solver. Tests change identifiers,
polygon dimensions and coordinate frames independently of those examples.

The friendly editor converts g/mm and physical Euler X→Y→Z angles into the same
typed request. It never estimates mass, stiffness or strength. The loopback
`POST /evaluate-assembly` and `--assembly-input experiment.json` CLI recompute
from the input request; stored result fields cannot establish a pass.

## Limits retained

This is a polygonal sheet/panel assembly model, not arbitrary solid CAD, contact
dynamics, collision resolution or a general fabrication compiler. Stages declare
hypothetical physical states; they do not approve cutting, consume stock, complete
operations or create evidence. Gabo's fabrication rules remain authoritative for
execution. The production stand compiler still supports its declared family.
Unknown material/contact data remains unresolved; scalar friction, joint and beam
checks retain the limits documented in the stage-mechanics handoff. No physical
success follows from a modeled pass.
