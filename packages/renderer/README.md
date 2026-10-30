# SVG renderer

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #8. Status: not implemented.

Render authoritative SVG steps and cut layouts from compiled geometry and domain
operation metadata. Include stable part/operation IDs, numeric dimensions,
cut/fold symbols, arrows, tools and required checkpoints. Keep the camera deterministic.

No independent model-created part geometry. Identical render dependency inputs
produce identical panels; changed dependencies regenerate affected panels only.
Cache reuse never proves physical verification freshness.

First deliverable: one tested stand parameterization, stock/BOM and a complete
SVG operation sequence. Add a meaningfully different inventory geometry as
measured tests support it. See [architecture](../../docs/architecture.md).
