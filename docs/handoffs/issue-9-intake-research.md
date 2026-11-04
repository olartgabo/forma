# Intake research provider and API handoff

Draft for [#9](https://github.com/olartgabo/forma/issues/9). @ResniDev owns the
gateway and prompts. @olartgabo owns the shared route, project scope and receipts.
Agree on the route and generated contract before either lane changes shared API
files. This draft describes the proposed contract and checks.

## Research and adjudication

Start with the supported tabletop stand workflow. Before dispatch, turn the
approved public brief into named requirements using supported categories. An
essential requirement without a check stays visible as unverified.

1. A Muse Spark scout searches for comparable projects. It returns sourced
   approaches, the materials and tools they assume, and possible adaptations.
   Each retained claim needs a completed search and a provider citation covering
   that claim.
2. In parallel, a separate Spark analyst reads the same public brief and a
   static catalog of supported operations and joints. It maps requirements to
   applicable checks and names ways an approach could fail. It gets neither
   the scout's recommendation nor private inventory, and has no tools.
3. FORMA validates both outputs and runs applicable existing stand search,
   measurement decision and fabrication checks on the server's saved inputs
   when prerequisites hold. Record what passed, what failed and what could
   not be checked. Example tutorial dimensions never become inventory inputs.
4. A fresh Spark adjudicator sees bounded finding IDs, normalized claims and
   safe check codes. It has no tools. It proposes an approach worth trying, a decisive missing
   input or a blocker. It must cite the findings and check IDs behind its choice.
   FORMA validates those IDs and enforces the check results. Code keeps
   conflicting findings visible and prevents an unresolved or failed essential
   check from becoming a pass. Skip adjudication when an existing check already
   decides the outcome.

FORMA coordinates the roles. Meta hosts inference and web search through the
documented Responses API. Reuse the existing server-side transport. Use one-shot
requests without shared conversation history. A separate Meta agent deployment
API was not identified.

- [Search grounding](https://dev.meta.ai/docs/search-grounding)
- [Responses API](https://dev.meta.ai/docs/protocols/responses)
- [Tool calling and built-in call limits](https://dev.meta.ai/docs/tool-calling)

## Proposed contract

An owner-scoped research action accepts an expected inventory revision, an
explicitly approved public search brief, search consent and an idempotency key.
The builder reviews the exact public brief before dispatch. Compose it from
generic goal, material, tool and constraint categories. FORMA may show private
project context locally to help the builder choose those categories. Photos,
private notes, identifiers, inventory measurements and raw project text stay out
of the search request. The provider gets the approved brief and static role
instructions, using Standard mode and requesting `store: false`. Confirm actual
provider retention behavior before enabling the feature. The analyst also gets
the static catalog. The adjudicator receives bounded research and check codes
derived without private text, project identifiers or actual measurements.

Return an opaque research ID and two separate fields. Research coverage is
complete, partial, no sources, unsupported or unavailable. The recommendation is eligible to
propose, needs input, blocked or undetermined. Each decision names the supporting
finding and check IDs where available. Return up to four distinct findings with
short claims, source titles, public HTTPS URLs and applicability caveats. A
malformed, skipped or late adjudication can leave useful references with an
undetermined recommendation. A verified citation identifies the source of a
claim. The source may still be wrong or unsuitable.

Implement API-local Pydantic records and generate browser types through the
existing exporter. Bind results to the owner, project, approved brief, saved goal
and exact inventory revision. The design route may accept an optional research
ID. It resolves and rechecks the result server-side, including after any
in-flight proposal, and gives Muse bounded hints from an eligible result.
Excluded goals cannot enter the research-assisted design path. Treat hints as
untrusted data in a delimited prompt section. Forbid tool or
instruction fields in findings. Use existing supported-operation, fabrication,
measurement and compiler gates for all designs. Keep research separate from
inventory, plans and Proof. The ordinary design request needs no research ID.

## Dispatch rules

- Feature off by default. Stop excluded requests before dispatch when the
  existing scope rules can identify them. Ask for clarification if the public
  brief cannot be narrowed to a supported, low-risk goal. Reject out-of-scope
  suggestions from either task.
- Cap each investigation at three model invocations and one built-in search,
  with a shared 20-second starting deadline and explicit per-call token limits.
  Use Meta's built-in call limit for the scout. Reserve provider budget before
  dispatch and enforce owner/global concurrency. Skip adjudication if time
  expires. Prohibit recursive delegation and automatic retries. Design is a
  separately requested action with existing limits. Reuse feedback on checked
  failures for a bounded correction only where the existing runtime supports it.
- Reuse the durable receipt and unknown-outcome rules from the
  [construction handoff](muse-construction.md). Replay identical requests,
  reject changed payloads and stale revisions, and block repeat paid dispatch
  after an unknown outcome until reconciled. Recheck the snapshot before
  returning or using a result. An owner can continue without research while
  a research receipt is unresolved. Discard stale and deleted results. Active
  builds use the history-aware repair path.
- Only the scout can use Meta's built-in web search. Validate response size,
  terminal status, tool output, citation coverage and URLs. FORMA does not
  fetch cited URLs. Store bounded sanitized findings and safe counters only.
  Keep queries, raw provider content and credentials out of logs and Proof.
  Capture per-task duration, status, search count and reported token usage.

## Acceptance before enabling

- [ ] Offline gateway tests cover successful cited output, skipped search,
      malformed or spoofed citations, injection, disallowed URLs, provider failures,
      timeout and a partial result. Assert each role receives only its allowed
      inputs, tools and budget. Check every outbound request for private fields.
- [ ] Test adjudication on conflicting findings, fabricated IDs, missed
      requirements, skipped adjudication and attempts to promote a failed check.
      Assert local check outcomes take precedence even if every agent agrees.
- [ ] API tests cover consent, feature off, cross-owner access, stale results,
      deletion, overlapping requests, exact replay, changed-payload conflict and
      unknown outcomes without repeat dispatch.
- [ ] Design tests prove that useful hints reach Muse as advisory context,
      forged or stale IDs are rejected, and research cannot approve an unsupported
      operation, satisfy a missing measurement or alter any physical record.
- [ ] A separately authorized live probe on a generic public brief verifies
      search, citation mapping and reported usage on the deployment account. Record
      actual outcome and latency in model compatibility. Keep the feature disabled
      if live prerequisites or provider controls fail.

The live verification window is expired. This draft involved public
documentation reads and no authenticated provider calls or physical tests.
