import type { RepairPatch } from "./generated/contracts";

export type MuseCandidateMergeResult = {
  next: readonly RepairPatch[];
  added: number;
  skipped: number;
  addedIds: readonly string[];
};

export function mergeMuseCandidates(
  current: readonly RepairPatch[],
  incoming: readonly RepairPatch[],
  cap = 3,
): MuseCandidateMergeResult {
  const seen = new Set(current.map((candidate) => candidate.id));
  const capacity = Math.max(0, cap - current.length);
  const addedList: RepairPatch[] = [];
  for (const candidate of incoming) {
    if (seen.has(candidate.id)) continue;
    seen.add(candidate.id);
    if (addedList.length >= capacity) continue;
    addedList.push(candidate);
  }
  return {
    next: addedList.length > 0 ? [...current, ...addedList] : current,
    added: addedList.length,
    skipped: incoming.length - addedList.length,
    addedIds: addedList.map((candidate) => candidate.id),
  };
}

export function museCandidateLabel(
  candidateId: string,
  museCandidateIds: ReadonlySet<string>,
): string {
  return museCandidateIds.has(candidateId)
    ? "— Muse proposal (unverified) "
    : "";
}

export function isCandidateSetCurrent(
  startVersion: number,
  currentVersion: number,
): boolean {
  return startVersion === currentVersion;
}
