import type {
  CandidateOutcome,
  RepairSearchSummary,
} from "./generated/api-contracts";

export function searchStatusText(summary: RepairSearchSummary): string {
  const checked = `${summary.evaluated_count} of ${summary.generated_count}`;
  if (summary.status === "found")
    return `Checked ${checked} candidate repairs. The ones that passed are ranked below.`;
  if (summary.status === "exhausted")
    return `Stopped after checking ${checked} candidate repairs, the search limit. None of those passed; unchecked candidates might.`;
  return summary.generated_count === 0
    ? "No candidate repair can be built from the remaining stock and tested profiles."
    : `Checked all ${summary.generated_count} candidate repairs. None passed.`;
}

export function candidateText(outcome: CandidateOutcome): string {
  const patch = outcome.patch;
  const what =
    patch.kind === "replace_part"
      ? `Replace ${patch.target_id} from ${patch.replacement_stock_id}`
      : patch.kind === "resize_part"
        ? `Resize ${patch.target_id} to ${patch.width_mm} × ${patch.height_mm} mm`
        : patch.kind === "replace_joint_profile"
          ? `Join ${patch.target_id} with ${patch.replacement_profile_id}`
          : `Change ${patch.target_id}`;
  const status: Record<CandidateOutcome["status"], string> = {
    ranked:
      outcome.preview_id === null
        ? `passed, rank ${outcome.rank}, not previewed (only the top 3 are)`
        : `passed, rank ${outcome.rank}`,
    infeasible: "did not pass",
    cycle: "would recreate an earlier plan",
    duplicate: "same result as another candidate",
    not_evaluated: "not checked (search limit)",
  };
  return `${what}: ${status[outcome.status]}`;
}
