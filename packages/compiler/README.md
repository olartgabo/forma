# Assembly compiler

Pure offline `forma_compiler.validate_plan(plan, *, process=None, allow_synthetic=False)`
returns a domain CompilerResult. It replays sheet-region, part, connector and joint
availability; rejection never mutates the immutable input. `accepted` means resource
and operation checks passed, not a physical function/safety test or stand-family
parameter compilation. The plan status is retained. The stand template in #8 owns
its device/angle/contact/footprint checks before calling this validator.

Coordinates are absolute in the original stock frame. Width/height represent the
occupied footprint after rotation; rotation metadata is checked against stock's
allowed rotations and is not applied twice. Features use local part coordinates.
Each cut consumes its complete source region; explicit offcuts retain source and
producer provenance. Unallocated area is waste and can never be reused. Disjoint
child/offcut footprints include measured kerf separation and cut edge margins.

Cuts require a server-reviewed `CutProcess` containing measured minimum kerf,
edge margin and scoped evidence. The authenticated service must supply its reviewed
catalogue, not accept profiles/process values authored by a model or arbitrary API
client. JointProfile status, limits and evidence IDs likewise come from that trusted
catalogue; #8 resolves their evidence before offering a stand. This validator cannot
authenticate a real-world claim by inspecting an evidence description.

`allow_synthetic=True` is an explicit fixture-only escape for process evidence with
synthetic provenance; default calls reject it. Synthetic tests are not measurements,
bench tests, supported joint promotion or evidence of a usable object. Current real
materials/profiles remain blocked on #2. No network/provider/database/UI dependencies.

Run `uv run --locked pytest packages/compiler/tests`. The root check includes these
tests, schema freshness, formatting, lint, web types and build. See the issue #5 handoff.
