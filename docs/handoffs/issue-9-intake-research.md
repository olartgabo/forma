# Intake research provider and API handoff

Implementation for [#9](https://github.com/olartgabo/forma/issues/9).
@ResniDev owns the gateway and prompts. @olartgabo owns the project API and
workbench. The request and result are API-local Pydantic records with generated
browser types.

## What runs

The initial release covers the existing triangular tape stand family. The
builder chooses a generic phone stand or reading stand brief and explicitly
consents to sharing the visible public text and limited option comparisons.
The builder can flag essential plug
clearance, which this workflow reports as unsupported. The ordinary stock
search remains available.

FORMA runs the stock search on the saved project before spending provider calls.
Only candidates with passing compiler, canonical geometry and fabrication-order
checks enter research. Missing inputs use the existing measurement decision
service when it can identify a question. A hard stock failure, unsupported
requirement or exhausted search has its own result. A search budget limit leaves
feasibility unresolved.
The missing-input result links directly to the workbench measurement controls.
Opening them fetches the current deterministic decision and focuses the form.
A stale decision clears the old form. Opening it saves nothing.

For eligible inputs, a Muse Spark scout looks for cited comparable projects.
A separate analyst reads the public brief and static stand catalog to flag a
relevant check family when there are two checked options with a measurable
difference. FORMA sends those two tasks in parallel. A fresh adjudicator can
recommend an option or abstain. A recommendation identifies the cited finding
and a directional tradeoff such as less tape or a deeper base. The server checks
that the source exists and that the option has that tradeoff in the current
engine search. The connection between the source and the choice remains advice.
With one checked option or no comparable difference, only the scout runs.

The workbench shows sources, coverage and the next action separately and marks
the source the recommendation used. The builder can bring those same checked
candidates into the existing comparison and see the rationale and cited claim
on the suggested option. Current stock choices stay usable during compatible
research and provider failures. An unsupported essential requirement or stale
inventory clears those choices. A pending request restores its essential clearance
requirement before stock search can run. After replay, the current form retains the
requirement for review. Selection uses the existing
synthesis route to recheck the search and save a preview. Activation requires
explicit approval. Research writes no inventory, plan, operation, or physical
evidence.

## API and privacy

- GET `/api/projects/{id}/synthesis/research` returns authenticated availability.
  Enable with `FORMA_INTAKE_RESEARCH=1` only after live acceptance.
- POST to the same route accepts the expected inventory revision, explicit
  consent, the bounded brief options and an idempotency key. It returns source
  coverage, a local decision, and optional checked candidates and recommendation.
- The server reserves a durable receipt before provider dispatch. Identical
  retries replay a terminal response. Changed inputs conflict. Project deletion
  purges its receipts. Recheck inventory, active plan, and resolved search
  context before returning a result. New paid dispatches for the project are
  blocked after an unknown provider outcome.
- The server limits active research to one request per owner and two overall.
  A short capacity lease survives project deletion without retaining project
  data. Expired leases free capacity after a crash while the affected project's
  unresolved receipt continues to block another dispatch.
- The gateway makes up to three model requests and one built-in web search
  with one 20-second budget, per-role token limits, and zero automatic retries.
  Only the scout has a tool. All roles request `store: false` in Standard mode.
  Exact measurements, private notes, media, project IDs and user IDs stay
  out of the research requests. The result reports elapsed provider time and
  provider-reported usage when available. Keep raw responses out of storage
  and Proof.
- Findings retain bounded text with a provider citation over the claim.
  FORMA validates links and renders them as text and public HTTPS URLs.
  The citation identifies a source. Its claim remains advisory.

Provider references

- [Search grounding](https://dev.meta.ai/docs/search-grounding)
- [Responses API](https://dev.meta.ai/docs/protocols/responses)
- [Tool calling and built-in call limits](https://dev.meta.ai/docs/tool-calling)

## Acceptance before enabling

Offline route and gateway tests cover the connected checked-candidate path,
missing tools, unsupported plug clearance, impossible stock, stale results,
privacy, malformed citations, timeouts and idempotency. Browser tests cover
consent and review through the existing design controls with mocked transport.
The synthetic checks establish software behavior. Paired fixture runs hold
the findings and checked candidates fixed while the adjudicator recommends,
abstains, cites an unavailable source, or chooses the wrong depth direction.
An older receipt replays its sources and checked candidates without the
unattributed recommendation or another dispatch.

Run the three-arm replay with
`uv run --locked pytest -q -s apps/api/tests/test_intake_research_evaluation.py`.
It compares ordinary stock search, the real scout with adjudication omitted,
and the full route on the same inventory and brief. Report explicit useful
recommendations, correct abstentions, local API wall time and role call counts.
An independent fixture label checks whether the selected citation actually
supports the suggested tradeoff. A valid URL and a true dimensional comparison
can still produce poor advice. The stock search cannot represent essential
plug clearance, so the comparison records that gap separately.

The live verification window is expired. An authorized probe still needs to
confirm provider availability, retention behavior, citation shape and actual
usage on the deployment account. Compare the same confirmed briefs with ordinary
intake, search only, and full research before claiming an improvement. The paired
comparison must hold findings and engine results fixed to isolate adjudication.
Use provider-reported usage and billed cost where available, and have builders
choose an option or abstain against the same task criteria without seeing the
mode labels. Local replay time and call counts are software measurements.
Keep live, deterministic and physical outcomes separate.

The next candidate in the spec is a passive desk cable organizer. It needs its
own checked topology, measured stock and cable dimensions, reviewed cutting and
joint limits, canonical SVG and a recorded fit and retention test. The current
compiler covers the triangular tape stand. Phone and reading stands use that
same topology.
