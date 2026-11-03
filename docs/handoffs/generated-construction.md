# Generated construction and fabrication integration

The user asked to define a finished shape once and generate its construction
steps, rather than author every stage manually. This packet also incorporates
Gabo's fabrication safeguards at published head `df28f8f` (local integration
merge `b0ede0b`), preserving repair search and attached-base recovery.

## User flow

Open the direct engine lab, choose box, ramp or a flat polygon target, set its
dimensions and select **Generate construction steps**. The dimensions define
target geometry; the sequence is generated from its part/joint graph. Height
applies only to box and ramp; triangle and concave targets are flat panels.
The custom target editor remains available for other panel assemblies, but its
selected finished state is enough: generated intermediate states need no manual
setup. The example targets explicitly assume 100 g uniform panels and rigid
connections; these are invented inputs, not inferred material properties.

Each generated step supplies an instruction, dependencies, participating parts,
active joints and a calculation from the existing generic physical producer.
An upright part before joining is a separate unsupported component, so the view
warns that support is not established. The generator never inserts a fictional
hand, jig or temporary contact to obtain a pass. Step navigation is read-only.

## Generation contract

`generate_construction(ConstructionRequest)` expands the supplied target graph
deterministically, preferring sources with explicit normalized contacts, placing
adjacent sources, connecting available declared joints and adding a final
inspection. It has no stand-name dispatch or prewritten per-shape step list.
Every prefix is evaluated through `evaluate_assembly`. Future sources and joints
are excluded; final reaction/strength demands are not copied into a different
intermediate load path. Source mass and geometry remain those of the target.

Unplaced parts are outside the proposed assembly load model, not claimed to be
uncut or nonexistent. These are planned states, not collision-free motions,
fabrication readiness, physical completion or manufacturing approvals.
`bind_operations` adds external operation IDs without recomputing the physics;
the adapter must validate the associated BuildPlan and readiness separately.

## Compatibility with Gabo's engine

The lab's fabrication checkbox explicitly opts into fixed **synthetic** resources:
one 1000×1000×2 mm sheet, 5000 mm of 25 mm tape, 2 mm kerf, 4 mm edge margins and
80 mm of tape per joint. The values, process and profile evidence are labeled
fixtures. The adapter never enlarges stock to make a design fit. Production
stock/process capture is not implemented by this diagnostic bridge.

For single-facet rectangular sources, `build_fabrication` proposes a real BuildPlan
containing a rectangular cut, per-panel inspections, tape joints and final
inspection. Dependencies follow the generated source/joint relationships. Every
operation is associated once with the corresponding construction step, including
the global cut at the first placement. Instructions are rendered from actual
operation dimensions, coordinates, tape lengths and checkpoints.

The adapter calls the existing `fabrication_report` and compiler with explicit
synthetic mode. Gabo's code alone determines tool/material/access blockers,
supported order and operation readiness. It consumes the current inventory,
not an already-spent future projection. No PhysicalEvent or completion is created;
the initial report has no attached joints. Geometry/resource changes bind new
deterministic plan and report identities, and replay regenerates the report.

Nonrectangular and multi-facet sources can receive proposed assembly states but
are rejected by this manufacturing adapter. They are never fabricated as their
bounding rectangles. Too-small stock, insufficient tape and joints shorter than
the supported tape fixture are explicit blockers. Real measured process/profile
data and user approval remain necessary outside the diagnostic.

## Reproduction

The loopback `POST /generate-construction` accepts a parametric shape, an editor's
finished stage, or a typed generic target. It returns the generated construction,
actual fabrication report/BuildPlan when applicable, and explicit limitations.
Download and replay with:

```powershell
uv run --locked python -m forma_stability --construction-input experiment.json
```

Replay uses the saved request and recomputes; stored results are ignored. Tests
cover graph changes and arbitrary names, stage support, no future load reuse,
actual box/ramp fabrication, unsupported polygon cutting, stock shortages,
operation binding, deterministic replay, origin checks and browser navigation.
No provider calls or physical observations are used.
