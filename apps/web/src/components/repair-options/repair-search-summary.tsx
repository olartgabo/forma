import type { RepairSearchSummary } from "../../lib/generated/api-contracts";
import { candidateText, searchStatusText } from "../../lib/repair-search";

export default function RepairSearchSummaryPanel({
  summary,
}: {
  summary: RepairSearchSummary;
}) {
  return (
    <section className="repair-search" aria-labelledby="repair-search-title">
      <h4 id="repair-search-title">Repair search</h4>
      <p>
        <strong>{searchStatusText(summary)}</strong>
      </p>
      <p className="help">
        Repairing {summary.target_ids.join(", ")}. Ranking uses only known
        terms: lost and undone work, preserved steps and measured material.
        Time, purchase price and strength stay unknown. No stability check
        covers these repairs yet, so stability is unverified, not passed.
        Searching records no work; nothing changes until you approve one
        revision below.
      </p>
      <details>
        <summary>Every candidate checked</summary>
        <ul>
          {summary.outcomes.map((outcome) => (
            <li key={outcome.patch.id}>
              {candidateText(outcome)}
              {outcome.blockers.length > 0 && (
                <ul>
                  {outcome.blockers.map((blocker, index) => (
                    <li key={`${index}-${blocker.code}`}>{blocker.message}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
