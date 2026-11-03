# Materials, geometry and piece references

Construction proposals now accept `ConstructionResources`: exact inventory
revision, existing stock IDs and usable regions, tools, cutting process and
profile evidence, and explicit connector/profile/access bindings per joint.
The adapter proposes allocations across supplied regions and allowed rotations,
then calls Gabo's existing production fabrication report and compiler. It does
not enlarge stock, manufacture test evidence, consume inventory or approve work.
The bounded first-fit search may reject a layout that a better packing search
could find; its rejection does not prove global infeasibility.

The direct lab defaults to material entry with unknown measurements and no
confirmed tools/process. Enter available sheets and connectors, or import a
resource snapshot. Missing reviewed process/profile information stays a blocker.
Locally imported records are unverified claims, not authenticated catalogue data.
Synthetic demonstrations remain a separate explicit option. Resource modes cannot
be mixed. Parametric targets using actual materials no longer inherit invented
100 g panel masses; those mechanics remain unresolved until supplied.

## Broader targets

In addition to existing targets and arbitrary custom panel assemblies, the lab
accepts regular polygon panels, polygon enclosures and zigzag screens with
3–12 sides/panels. Geometry and graph size change with the inputs; all use the
same construction generator. Enclosures and screens consist of rectangular
walls; their bottom-edge ground support is not inferred. Polygon-panel assembly
geometry is supported, but nonrectangular cutting remains unsupported by the
fabrication bridge. No bounding rectangle is substituted for the requested cut.

## A shared piece vocabulary for AI and diagrams

`PieceAnnotation` carries a user/model proposed name, role and classification.
Every source part receives a `PieceReference` with an immutable-part-ID-derived
reference and a geometry classification calculated by the canonical polygon
validator. Duplicate friendly names remain distinguishable by references.
Renaming, changing dimensions or reordering the same part IDs preserves those
references. Replacing a physical piece requires a new part ID. References are
assembly-scoped, not cross-project object recognition.

Computed geometry classes and proposed semantic classifications remain separate.
For example, MetaMuse may call a piece “rear brace”; the engine can establish
that its declared geometry is rectangular, but cannot infer actual material,
mass, visibility, attachment, strength or real-world identity from that name.
Names never rewrite mechanical IDs or fabrication operation references.
The same catalog supplies construction instructions, 3D labels and cut/tape
instructions. Untrusted labels are rendered as text.

MetaMuse remains the proposal/perception engine. Typed targets and annotations
give it a consistent vocabulary; deterministic results expose blockers it can
reason about. This packet does not add a vision model, perform object tracking,
change provider prompts, or claim a new live model test.

## Connected consumer

The project-scoped construction endpoint consumes typed target proposals and
piece annotations while resolving inventory and reviewed process/profile context
on the server. Callers cannot supply replacement stock, profile evidence or
process evidence to that route. Exact revision checks and owner isolation apply.
An active build uses Gabo's existing history-aware fabrication/repair flow rather
than fresh-build allocation. The result is read-only and never activates a plan
or completes an operation. The existing stand design/model flow is not silently
changed into an unrestricted shape generator.

## Verification and limits

Regression checks cover real-contract stock allocation, shortages, unknown
measurements, rotation, missing tools/profile/access evidence, immutable resource
inputs, no mixed synthetic mode, stable references, unsupported manufacturing,
and different generated graph sizes. Browser checks exercise material entry and
reference consistency. Fixtures test software contracts; none establish actual
inventory, physical success or measured model-performance improvement.
