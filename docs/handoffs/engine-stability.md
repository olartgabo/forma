# Stability engine: initial S0 contract slice

Issue [#142](https://github.com/olartgabo/forma/issues/142), November 3, 2026.
Owner: ResniDev. Feature reviewer and geometry interface partner: olartgabo.

This slice introduces validated quantities, analysis identity, policy and reports
in `forma_domain.stability_contracts`, with generated JSON Schema, OpenAPI
components and browser types. It does not calculate stability or expose a route.
S0 is still pending shared geometry/stage agreement; S1–S7 are not implemented.
Schema validation does not authenticate evidence, establish freshness or prove a
physical result. API consumers must resolve all references in an authorized
project snapshot before using these records.

## Consumer agreement

Import the Python records from `forma_domain.stability_contracts`. Browser types
come from the existing domain generator; do not maintain a second schema.
Measurements can be a finite scalar, ordered inclusive interval or unknown.
Units are explicit SI. Provenance, confirmation, evidence and correlated
dependencies travel with the estimate. An interval is not automatically a
defensible physical bound; the future engine must validate its applicability.

An analysis identifies the exact plan, inventory, construction history, geometry,
evidence and profile revisions. The future server must reject stale contexts and
derive hashes from normalized authoritative inputs, never from display rounding.
Identity fields alone do not implement a cache or revision check.

Reports cover a declared case/check matrix. Missing required checks and failed
computation cannot support an overall modeled pass. Physical observations are
separate references to existing evidence; a modeled pass creates no physical
event. A tipping result does not establish phone retention, sliding resistance,
joint capacity or cardboard strength.

## Geometry handoff still required

[#144](https://github.com/olartgabo/forma/issues/144#issuecomment-6596884972)
owns the canonical pose producer; #141 owns chronological fabrication semantics.
No competing pose producer or AssembledGeometry schema is introduced here.
Before S1 integration, agree and publish:

- Right-handed physical frame: x across, y along the base, z upward; explicit
  support plane and SI conversion from the existing mm/g/degree inputs.
- Physical transforms and part/facet IDs, preserving folded-part mass totals.
- Active stage-specific contacts and attachments, excluding future braces.
- Nominal versus observed geometry and explicit contact assumptions.
- Canonical geometry hash and binding to the exact operation/history state.

Camera motion and exploded display offsets never alter these inputs. Until the
shared producer exists, analytic reference cases may test mathematics but cannot
satisfy connected acceptance. The next slice must consume that producer, not
infer assembled poses from flat rectangles or SVG pixels.

## Applicability and numeric policy for S1

| Check | Supported target | Required unresolved result |
| --- | --- | --- |
| Whole-assembly tipping | Horizontal, coplanar support; gravity only; explicitly assumed rigid assembly; measured or justified bounded mass/COM | Missing mass/contact inputs need measurement; unsupported load or stage stays unsupported |
| Phone retention and sliding | Separate contact model with evidence | No inference from a whole-assembly tipping pass |
| Joint strength and deformation | Separately calibrated later models | Not verified by dimensional joint profiles |
| Dynamic response | Separate future capability | No physical claim from animation |

Caller-selected physical clearance and numerical tolerance must be separate.
For the future signed-clearance test, a lower bound strictly above the required
clearance plus tolerance may pass; an upper bound below the required clearance
minus tolerance fails; the boundary/overlap is indeterminate. These are proposed
engine semantics, not a solver implemented by this contract slice. No default
engineering reserve, material property or maximum payload is invented.
Finite sampling alone cannot justify a conservative interval guarantee.

## Dependencies and attribution

This slice uses the already pinned Pydantic dependency and adds no numerical
distribution. Retain the #142 choices for S1: NumPy for numerical operations and
Shapely for planar support geometry, behind small adapters. Shapely requires an
explicit projection into the support frame; it is not a 3D mechanics solver.
See the [Shapely manual](https://shapely.readthedocs.io/en/stable/manual.html).

The [Shapely source license](https://raw.githubusercontent.com/shapely/shapely/main/LICENSE.txt)
is BSD-3-Clause; [GEOS](https://libgeos.org/) has separate LGPL terms. NumPy's
[license](https://numpy.org/doc/stable/license.html) requires retained notices.
Before adding the numerical stack, select and pin exact releases through the
package manager, retain the installed distribution and bundled-library notices,
and verify Python 3.12 on Windows and the deployed Linux ARM64 target. No binary
compatibility or transitive-license audit is claimed by this planning decision.
SciPy/HiGHS remains P1; PyNite and dynamics remain later evidence-gated work.

## Remaining delivery gates

1. Agree the shared geometry/stage contract and finish S0 mass/contact/load models.
2. Implement S1 with independent analytic boundary, invariance and invalid-input
   tests; preserve unknown mass, phone contact and material properties.
3. Connect scoped immutable reports, stale-context rejection and SVG fallback in
   S2 before claiming a usable stability feature.
4. Add bounded Muse tools, shared viewer overlays and actual physical observations
   in S3/S4. Existing live-call windows and STOP controls remain unchanged.

Run domain tests, generated-contract freshness and the repository check command.
Independent Sol/Terra review is required before publication; feature review and
checks on the exact published head remain required before merge. None of these
software checks establishes a physical pass.
