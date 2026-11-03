# Evaluation harness

Owner: @olartgabo. Reviewer: @ResniDev. Issue: #15.

`forma_eval` turns recorded attempts into the counts the
[evaluation protocol](../../docs/evaluation-protocol.md) asks for. It reads a
manifest the team writes, one entry per attempt, and the Proof JSON export of
each FORMA attempt. It invents no result: every rate is a numerator over a
denominator from those records, and an empty denominator is printed as `n/a`
with the reason.

```sh
uv run --locked python -m forma_eval path/to/manifest.json > results.md
```

The run exits 1 when a manifest label contradicts its Proof export, so a
contradicted table is not published by accident.

## Manifest

```json
{
  "attempts": [
    {
      "id": "a-damaged-joint-1",
      "inventory": "A",
      "case": "damaged_joint",
      "method": "forma",
      "evidence_level": "physically_passed",
      "builder": "team",
      "proof_export": "exports/a-damaged-joint-1.json",
      "human_corrections": 1,
      "questions_asked": 2,
      "notes": "Rear joint tape tore during the functional test."
    }
  ]
}
```

- `case`: `none`, `missing_connector`, `dimension_mismatch`, `damaged_joint` or
  `infeasible`. Give `rejection` with the concrete blocker for an infeasible case.
- `method`: `forma`, `single_prompt`, `vision_chat` or `fixed_template`.
- `evidence_level`: `fixture_only`, `compiler_validated`, `bench_tested`,
  `physically_attempted` or `physically_passed`. Only the last two enter
  completion and recovery rates.
- `proof_export`: path relative to the manifest. Required for a physical FORMA
  attempt; baselines have none.
- `human_corrections`, `questions_asked`: counted by the observer; omit when
  not recorded.

## What comes from Proof

Passed functional test on the active version, recorded failures (failed checks
and damage), recovery through an approved revision, kept and lost work in
approved revisions, recorded sheet and connector waste, and the time from the
first recorded failure to the last passing test. Times are server ingestion
times, not stopwatch measurements.

A passed FORMA build counts as a recovery only when Proof also records a
failure and an approved revision. A disruption label alone does not establish
recovery. Baseline recovery uses the observer's disruption and outcome labels.
Proof-derived preservation, waste and recovery timing include only physical
attempts. Fixture, compiler and bench records do not contribute to those totals.

## Limits

Latency and model usage, baseline transcripts and consent records stay in the
attempt notes and logs; the harness does not read them. Synthetic tests in
`tests/` exercise the counting rules and one recorded software history; they are
not build results.
