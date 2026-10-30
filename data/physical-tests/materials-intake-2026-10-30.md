# Materials intake, October 30, 2026

Issue: [#2](https://github.com/olartgabo/forma/issues/2).
Owner: @olartgabo. Reviewer: @ResniDev.

Status: user-reported availability. No measurements, photographs, bench tests
or build attempts have been supplied. This is an intake note, not a compiler
inventory fixture or a tested joint profile.

## Original observation

The user reported:

> raspbery pi 5 8gb ram, arduino, esp32, a lot of cardboard, glass and plastic bottles, that kind of stuff

| Reported item | Known fact | Role in the first supported stand experiment |
| --- | --- | --- |
| Cardboard | Available; quantity described as “a lot” | Candidate sheet stock; individual sheets still need measurement |
| Raspberry Pi 5 | 8 GB RAM model reported | No electronics role in the P0 sheet-material stand |
| Arduino | Available; model/count unknown | No electronics role in P0 |
| ESP32 | Available; model/count unknown | No electronics role in P0 |
| Glass bottles | Available; dimensions/count/condition unknown | Outside the current rectangular sheet-stock family |
| Plastic bottles | Available; dimensions/count/condition unknown | Outside the current rectangular sheet-stock family |

“A lot” does not establish a sheet count or usable area. No item has been
assigned a measured stock ID, and neither inventory A nor B is confirmed.
No consent to hosted-model transfer or public photo sharing has been recorded.

## Next measurement session

1. Select one or two actual cardboard sheets for inventory A. Give each a unique
   source label and retain the label in photos and later cut/offcut records.
2. Record width, height and thickness in millimeters, measurement method,
   corrugation/orientation, folds/tears and the actually usable region. Record an
   uncertain reading as unknown; do not estimate thickness from a photo.
3. List the tools and connectors actually available. Ruler, cutting tool, tape,
   string and glue availability are all currently unknown.
4. Identify a second, meaningfully different measured sheet/connector selection
   for inventory B. Differences must affect geometry, allocation or joining.
5. Photograph the labeled sources with a measurement reference. Retain original
   images privately under ignored `data/physical-tests/private/`; publish only
   consented, redacted evidence with its provenance.

The domain owner converts these observations into typed fixtures after #3 lands.
Do not fill `fixtures/inventory_A.json` or `inventory_B.json` with invented
dimensions to unblock compiler development.

## Bench sequence to perform

All three strategies below are proposed experiments from the spec, with no
physical result or supported limits. Confirm actual tools and material before
starting. Keep one record per attempt, including failures.

| Experimental strategy | Measurements and observations to capture |
| --- | --- |
| Tab/slot | Sheet thickness, tab/slot dimensions, edge distance, orientation, tool/kerf, measured fit, insertion/removal damage |
| Folded brace | Sheet thickness/orientation, crease location, resulting geometry, attachment access, springback, tearing and whether removal loses material |
| Tape or lash brace | Actual connector type/length, attachment geometry/access, grip/slip, connector consumed, damage or loss on removal |

If a required connector is unavailable, record that blocker. Do not label an
unattempted strategy failed or promote one as supported without evidence.
Use [joint-profiles.md](../../docs/joint-profiles.md) for profile record fields
and [BUILD-LOG.md](BUILD-LOG.md) for each real attempt.

## Functional test to agree before building

Proposed procedure, awaiting actual device and geometry: on a named flat desk
surface, place the chosen phone in the completed stand, observe it for 60
seconds, gently tap its screen, and perform three insertion/removal cycles.
Record the result of each part of the procedure, including slip, tipping,
deformation or joint separation. Stop the attempt if the device cannot remain
supported. A result applies only to the recorded conditions.

Before this becomes an executable test, record the actual device/model and
measured mass, stand/support angle, contact geometry, surface, operator and
test date. None is known yet. The 60-second duration and three cycles are a
proposed protocol from spec section 4.1, not observations or load limits.

## Evidence state

- Measured inventories: none recorded.
- Physical joint attempts: none recorded.
- Stand build attempts: none recorded.
- Physical passes: none recorded.
- Blocking facts: dimensions/thickness/condition, tools/connectors, photos and
  consent, test device/mass/geometry, actual physical attempts.

Issue #2 remains open until those observations and attempts meet its acceptance
criteria. No G1/G2/G3 gate is established by this intake note.
