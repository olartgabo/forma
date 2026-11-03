import type { MaterialTransaction } from "./generated/contracts";

export function recoverableRegionIds(
  transactions: readonly MaterialTransaction[],
  stockId: string,
): string[] {
  const lost = new Set<string>();
  for (const item of transactions) {
    if (item.source_stock_id !== stockId) continue;
    if (item.kind === "waste" && item.unit === "mm2" && item.source_region_id) {
      lost.add(item.source_region_id);
    } else if (item.kind === "salvage" && item.output_region) {
      lost.delete(item.output_region.id);
    } else if (item.kind === "consume" && item.source_region_id) {
      lost.delete(item.source_region_id);
    }
  }
  return [...lost];
}
