# Issue 9 source-grounded investigation handoff

This slice builds on PR #179. The gateway owns retrieved source excerpts and
bounded evidence assessment. The project API keeps the current request and
response schema. The existing `findings[].claim` field carries the retrieved
excerpt for new results. The recommended candidate and source index keep
their existing meaning for the workbench. Older receipts preserve their
references but lose recommendations made before this evidence check.

Acceptance requires the paired replay to preserve both useful recommendations
and abstain on the tape-hinge citation. An eligible recommendation must go
through the existing scoped selection and compiler preview. Missing
measurements, unsupported requirements and stale project snapshots must
still stop the appropriate step. The compiler receives its usual typed inputs.

## Provider contract

Meta documents `include: ["web_search_call.results"]` for the Responses API.
Each `text_result` carries a URL, title and source snippet. Citation offsets
refer to the scout's own text. FORMA uses a citation to identify the retrieved
source, then gives the analyst the source excerpt. It never fetches the URL.
The adjudicator checks the excerpt in context and must use an allowed
source and tradeoff pair. FORMA checks the exact quote, the pair and the
engine comparison. The roles still judge whether the evidence is relevant.
[Meta search grounding](https://dev.meta.ai/docs/search-grounding#inspect-the-raw-search-results)

## Checkpoint

- Branch `codex/issue-9-source-grounded-investigation`, based on `43d5256`.
  Runtime changes are in `intake_research.py` and `intake_research_muse.py`.
  No public schema changes. Domain and API contract freshness checks passed.
- The three research pytest modules passed 51 tests. Full investigation made
  2 of 2 useful recommendations and 6 of 6 correct abstentions on eight
  scripted briefs. The earlier replay had 5 of 6 correct abstentions. The
  revised workflow made 11 scripted model calls, down from 14. The source-only
  arm used 5 calls and stock search used zero. Median local API wall time over
  the five eligible briefs was 109 ms for stock search, 140 ms for citations,
  and 142 ms for full investigation in this run.
- Ruff lint and formatting, Prettier, TypeScript, and the production web build
  passed. The web unit suite passed 193 tests and the devloop suite passed 18.
- The full Python run started before the quote-length fix and finished with
  1,834 passed and four skipped because they need a POSIX shell. The 51-test
  focused run above includes the final fix and both new regression cases.
- The browser regression passed at 390 px and 1280 px. It covered consent,
  stale research, fallback, cited candidate review and separate approval, and
  the existing measurement form opened without saving a value.
- Independent Sol review found that a one-character quote could pass the
  substring check. The gateway now requires a verbatim quote of at least four
  words. The regression submits punctuation from the tape-hinge excerpt.
  The reviewer checked the fix and found no further actionable issues.
- The deployment flag still requires live acceptance. The verification window
  was expired. Provider response compatibility on the deployment account,
  billed usage, live latency and builder choices remain unmeasured. No
  physical attempt or test result came from this replay.
