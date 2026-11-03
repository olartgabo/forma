# Stability S1

Pure `forma_stability.evaluate_stability(analysis: StabilityInput,
policy: AnalysisPolicy) -> StabilityReport` evaluates every declared and required named case.
Inputs are the mechanical consumer snapshot supplied externally by the canonical
geometry producer. This package produces no poses and imports no BuildPlan,
viewer, provider, storage or HTTP code. No canonical producer is connected yet.

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
Sliding, retention, joints, deformation and dynamics remain unsupported.

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
