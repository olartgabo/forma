# Stability S1

Pure `forma_stability.evaluate_stability(analysis: StabilityInput,
policy: AnalysisPolicy) -> StabilityReport` evaluates every declared and required named case.
Inputs are the mechanical consumer snapshot supplied by the canonical geometry
and measured-input adapters. The numerical evaluator has no viewer, provider,
storage or HTTP dependency.

`forma_stability.geometry.project_nominal_geometry` is the shared canonical plan
projection added under the user's November 3 ownership override. It validates
the supported stand topology through the existing family validator and produces
the Pydantic `CanonicalGeometryPreview` contract. Its nominal sheet facets,
conditional uniform-sheet centroids and ground footprint do not establish actual
mass, COM or contact. The default connected API shows this preview and missing mechanical inputs.
A current user-confirmed typed measurement batch can supply the measured
point-estimate adapter; its assumptions and limits remain explicit.

Consumers including the assembly viewer should reuse this producer. Planned
assembly and user-reported assembly have distinct stage labels; both remain
nominal geometry. Unsupported intermediate, damaged, detached and repaired states
fail visibly. Camera or exploded-view controls cannot alter physical coordinates.

Coordinates are SI metres, right-handed world x across, y rearward, z upward.
Each case explicitly selects present bodies and active supporting contacts.
The scalar path requires explicit rigid-assembly, horizontal-plane and
gravity-only applicability. Unknown inputs need measurement; intervals remain
indeterminate. Future bodies, nonhorizontal contacts and unsupported physics
cannot pass. Nominal versus observed and assumption IDs are preserved input
claims, not independent evidence verification.

Shapely validates planar contact polygons and forms their convex support hull.
NumPy computes the positive-mass weighted world COM. For each CCW hull edge the
engine computes signed inward perpendicular COM projection distance. The minimum
is the modeled margin; total mass times gravity times that distance is the signed
restoring moment. Convex hull assumes unilateral compressive support and explicit
assembly rigidity; it does not verify actual contact, attachment or friction.

The physical required margin is distinct from the numerical tolerance band:
`max(length_tolerance_m, relative_tolerance * longest_hull_edge_m)`. A clearance
strictly above required margin plus tolerance passes; strictly below required
margin minus tolerance fails; equality/overlap remains indeterminate. Negative
restoring moment is overturning. No force or moment strength check is inferred.
Optional scalar Coulomb sliding, supplied joint-demand/capacity and named beam
deflection checks now accept explicit inputs. They do not solve internal loads,
phone retention, general deformation or dynamics. See the
[stage mechanics scope](../../docs/handoffs/stability-stage-mechanics.md).

Reports evaluate the policy case/check matrix; missing required cases remain
unresolved. Optional input cases outside that matrix are also evaluated. The union is capped
at sixteen cases; exceeding it raises ValueError. One deterministic budget unit
is consumed for each present case; exhausted cases remain indeterminate. Typed
overlays bind exact case IDs and orientation labels to computed world COM,
support hull and critical edge. Case orientations describe already-transformed
world inputs: the engine never rotates bodies from an orientation label.

The cache hash binds normalized full inputs, policy, engine and NumPy/Shapely/GEOS
versions. ID-addressed collection order is normalized; polygon vertex sequence
is retained because changing it can alter polygon validity. Hashes establish no
freshness/authentication by themselves. Report physical evidence is always empty.

Run `uv run --locked pytest packages/stability/tests` for analytic reference
checks. These tests establish software mathematics only, never a physical pass.
Installed numerical distributions retain their own license notices; deployment
binary and transitive-license verification remains a separate integration gate.

## Direct engine lab

The primary flow now [generates construction proposals](../../docs/handoffs/generated-construction.md)
from a finished target, rather than requiring manual intermediate stages.
Rectangular-panel proposals can be assessed through the real fabrication engine
using an explicitly selected synthetic resource fixture. This never approves or
records physical work, and unsupported manufacturing operations remain blocked.

The [material and naming extension](../../docs/handoffs/material-construction.md)
accepts supplied stock/process records, variable-sided panel targets and stable
piece references. The authenticated project consumer resolves saved inventory
and trusted context server-side; the lab labels locally imported data unverified.

The primary [assembly editor](../../docs/handoffs/generic-assembly-diagnostic.md)
authors polygonal panels, edge joints and explicit physical stages. The generic
`evaluate_assembly` producer validates these declarations without stand-specific
IDs and shares the component solver with the existing stand adapter. This is
hypothetical mechanics, not general fabrication approval or observed evidence.

Run `uv run --locked python -m forma_stability --lab --port 3031` and open the
printed loopback URL. This user-requested diagnostic interface invokes the real
pure evaluator with explicitly hypothetical inputs. It stores no project evidence
and calls no provider. Exact JSON editing, downloadable input/report feedback and
CLI replay (`--input case.json`) make behavior reproducible. See
[the direct testing guide](../../docs/handoffs/stability-engine-lab.md).

The compiled-stand diagnostic has camera-only orbit/zoom and accepts explicit
physical stage snapshots through `forma_stability.stage.evaluate_stage`. The
opt-in cut-panel example evaluates three separately supported components. Stage
geometry and support do not come from the camera or the final assembly shortcut.
