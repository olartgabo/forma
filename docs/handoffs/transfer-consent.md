# One-request transfer consent

Photo intake and design dispatch now consume consent, matching the diagnosis
panel. Another success, failure or cancellation requires a fresh checkbox.
Explicit Retry same Muse request also requires renewed consent because a
pre-dispatch failure can leave no server receipt and a retry may contact Muse.
The stored request body/key remains unchanged; checking saved previews does not
start provider work. Unknown-outcome locks and session/revision epochs remain.

Muse authored this two-component change in parallel with the API usage lane.
Independent review approved it. The combined full project check passed 414
Python tests, 24 client tests, contracts, types, lint, formatting and build.

Actual browser checks against Muse Spark1.3 with the labelled synthetic photo:
- Intake: five labels, three questions, unknown measurements, 9,531ms; consent
  cleared and repeat transfer stayed disabled.
- Design: two model rounds/one snapshot tool, needs measurement, 8,547ms;
  consent cleared and ordinary Generate stayed disabled.
- Isolated QA API interruption: Retry was disabled after the connection failure,
  enabled only after fresh consent, and cleared consent on dispatch. The actual
  restored Muse request completed in 6,375ms with two rounds/one tool and
  measurement questions. The stable demo was not interrupted.

No model output was promoted to physical evidence, inventory, plan approval or
repair execution. Private DOM evidence and runtime data remain outside Git.
