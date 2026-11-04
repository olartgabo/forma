# Intake research provider and API handoff

Implementation for [#9](https://github.com/olartgabo/forma/issues/9).
@ResniDev owns the gateway and prompts. @olartgabo owns the project API and
workbench. The request and result are API-local Pydantic records with generated
browser types.

## What runs

The initial release covers the existing triangular tape stand family. The
builder chooses a generic phone stand or reading stand brief and explicitly
consents to the visible public text. The builder can flag essential plug
clearance, which this workflow reports as unsupported. The ordinary stock
search remains available.

FORMA runs the stock search on the saved project before spending provider calls.
Only candidates with passing compiler, canonical geometry and fabrication-order
checks enter research. Missing inputs use the existing measurement decision
service when it can identify a question. A hard stock failure, unsupported
requirement or exhausted search has its own result. A search budget limit leaves
feasibility unresolved.

For eligible inputs, a Muse Spark scout looks for cited comparable projects.
A separate analyst reads the public brief and static stand catalog to flag a
relevant check family. FORMA sends the two tasks in parallel. If usable sources
and two checked options remain, a fresh adjudicator can recommend a candidate
or abstain. It sees only bounded findings and relative tradeoffs such as whether
the second candidate uses less tape. FORMA translates its opaque selection
back to a candidate from the exact current engine search.

The workbench shows sources, coverage and the next action separately. The builder
can bring those same checked candidates into the existing comparison and
selection flow. Selection uses the existing synthesis route to recheck the
search and save a preview. Activation is a separate explicit approval. Research
writes no inventory, plan, operation, or physical evidence.

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
The synthetic checks establish software behavior.

The live verification window is expired. An authorized probe still needs to
confirm provider availability, retention behavior, citation shape and actual
usage on the deployment account. Compare the same confirmed briefs with ordinary
intake, search only, and full research before claiming an improvement. The paired
comparison must hold findings and engine results fixed to isolate adjudication.
Keep live, deterministic and physical outcomes separate.
