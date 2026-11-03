import type { PanelDiff } from "./generated/api-contracts";

export type PanelComparison =
  | { kind: "changed"; index: number; previous: number }
  | { kind: "added"; index: number }
  | { kind: "removed"; previous: number };

// Orders a repair preview's updated panels by their position in the new
// manual, then lists base-manual panels the revision no longer contains.
// `index` points into the preview manual and `previous` into the base manual.
export function panelComparisons(
  diff: PanelDiff,
  basePanelCount: number,
  previewPanelCount: number,
): PanelComparison[] {
  if (diff.changed.length !== diff.changed_from.length) {
    throw new Error("Each changed panel needs its original panel");
  }
  const inPreview = (index: number) => index >= 0 && index < previewPanelCount;
  const inBase = (index: number) => index >= 0 && index < basePanelCount;
  if (
    !diff.changed.every(inPreview) ||
    !diff.added.every(inPreview) ||
    !diff.changed_from.every(inBase) ||
    !diff.removed.every(inBase)
  ) {
    throw new Error("Panel comparison refers to a missing panel");
  }
  const updated: PanelComparison[] = [
    ...diff.changed.map((index, position) => ({
      kind: "changed" as const,
      index,
      previous: diff.changed_from[position],
    })),
    ...diff.added.map((index) => ({ kind: "added" as const, index })),
  ].sort((a, b) => a.index - b.index);
  return [
    ...updated,
    ...diff.removed.map((previous) => ({
      kind: "removed" as const,
      previous,
    })),
  ];
}
