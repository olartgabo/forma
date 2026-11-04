// Pure rules for recognised-item cards (#177 follow-up). No network or React.
import type {
  ItemIdentity,
  ItemProposal,
  RecognizedItem,
  Stock,
  VisibleBox,
} from "../../lib/generated/contracts";
// @ts-expect-error -- Node tests import TypeScript directly.
import { MATERIAL_CATALOG } from "../../lib/generated/material-catalog.ts";

export type CategoryInfo = (typeof MATERIAL_CATALOG.categories)[number];
export type CategoryId = CategoryInfo["id"];
export const CATEGORIES: readonly CategoryInfo[] = MATERIAL_CATALOG.categories;
const BY_ID = new Map<string, CategoryInfo>(CATEGORIES.map((c) => [c.id, c]));
export const CAPABILITY_TEXT: Record<string, string> =
  MATERIAL_CATALOG.capability_text;

export const GROUP_LABEL: Record<CategoryInfo["group"], string> = {
  paper_cardboard: "Paper and cardboard",
  wood_plant: "Wood and plant",
  plastic: "Plastic",
  foam_soft: "Foam and soft",
  tape_adhesive_tie: "Tape, adhesives and ties",
  connector_metal: "Connectors and metal",
};

export function category(id: string | null | undefined): CategoryInfo | null {
  return (id && BY_ID.get(id)) || null;
}

/** Where a box in pixels sits in normalised photo coordinates, and back. */
export function normalise(
  box: { x1: number; y1: number; x2: number; y2: number },
  width: number,
  height: number,
): VisibleBox {
  const c = (v: number, s: number) => Math.min(1, Math.max(0, v / s));
  return {
    x1: c(box.x1, width),
    y1: c(box.y1, height),
    x2: c(box.x2, width),
    y2: c(box.y2, height),
  };
}

export function iou(a: VisibleBox, b: VisibleBox): number {
  const w = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1));
  const h = Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
  const inter = w * h;
  const union =
    (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return union > 0 ? inter / union : 0;
}

/** The readable label for an identity; never claims more than it says. */
export function identityLabel(identity: ItemIdentity): string {
  if (identity.outcome === "catalog")
    return category(identity.category_id)?.label ?? "Unknown object";
  if (identity.outcome === "other")
    return identity.other_label ?? "Something else";
  return "Not sure what this is";
}

export function defaultItemName(
  identity: ItemIdentity,
  taken: readonly string[],
): string {
  const base =
    identity.outcome === "uncertain" ? "Unknown item" : identityLabel(identity);
  const used = new Set(taken.map((n) => n.toLowerCase()));
  if (!used.has(base.toLowerCase())) return base;
  for (let i = 2; i < 100; i += 1)
    if (!used.has(`${base} ${i}`.toLowerCase())) return `${base} ${i}`;
  return `${base} ${taken.length + 1}`;
}

export type Support =
  | {
      state: "available";
      kind: Stock["kind"];
      material: Stock["material"];
      note: string | null;
    }
  | { state: "not_available"; reason: string };

/** Fabrication support is shown on its own; it never follows from a name. */
export function support(identity: ItemIdentity): Support {
  const info =
    identity.outcome === "catalog" ? category(identity.category_id) : null;
  if (!info)
    return {
      state: "not_available",
      reason:
        identity.outcome === "uncertain"
          ? "Not identified yet; choose what it is to see if build rules exist."
          : "Identified; build rules not available yet.",
    };
  if (
    info.support !== "build_rules_available" ||
    !info.stock_kind ||
    !info.stock_material
  )
    return {
      state: "not_available",
      reason: "Identified; build rules not available yet.",
    };
  return {
    state: "available",
    kind: info.stock_kind as Stock["kind"],
    material: info.stock_material as Stock["material"],
    note: info.support_note,
  };
}

export function capability(identity: ItemIdentity): string | null {
  const info =
    identity.outcome === "catalog" ? category(identity.category_id) : null;
  return info ? info.capability : null;
}

/** Cards from a new proposal. Existing cards are never changed; a proposal
 * that overlaps an existing card on the same photo is skipped, so later
 * suggestions cannot overwrite the user's corrections or duplicate a card. */
export function mergeProposals(
  items: readonly RecognizedItem[],
  proposals: readonly ItemProposal[],
  mediaId: string,
  newId: (name: string) => string,
): { items: RecognizedItem[]; added: number; skipped: number } {
  const next = [...items];
  let added = 0;
  let skipped = 0;
  for (const proposal of proposals) {
    const box = proposal.box ?? null;
    const overlaps =
      box &&
      next.some(
        (item) =>
          item.media_id === mediaId && item.box && iou(item.box, box) >= 0.5,
      );
    if (overlaps) {
      skipped += 1;
      continue;
    }
    const name = defaultItemName(
      proposal.identity,
      next.map((i) => i.name),
    );
    next.push({
      id: newId(name),
      name,
      identity: proposal.identity,
      identity_source: "muse_suggestion",
      media_id: mediaId,
      box,
      box_source: box ? "muse_approximate" : null,
      visibility: proposal.visibility ?? "unclear",
      instance: proposal.instance ?? "single",
      stock_id: null,
      user_fields: [],
    });
    added += 1;
  }
  return { items: next, added, skipped };
}

type UserField = NonNullable<RecognizedItem["user_fields"]>[number];
function mark(
  item: RecognizedItem,
  field: UserField,
): RecognizedItem["user_fields"] {
  const fields = item.user_fields ?? [];
  return fields.includes(field) ? fields : [...fields, field];
}

/** A user correction of what the object is. */
export function correctIdentity(
  item: RecognizedItem,
  identity: ItemIdentity,
): RecognizedItem {
  return {
    ...item,
    identity,
    identity_source: "user",
    user_fields: mark(item, "identity"),
  };
}

export function renameItem(item: RecognizedItem, name: string): RecognizedItem {
  const next = name.trim().slice(0, 80) || "Item";
  return next === item.name
    ? item
    : { ...item, name: next, user_fields: mark(item, "name") };
}

export function setItemBox(
  item: RecognizedItem,
  mediaId: string,
  box: VisibleBox,
  source: "sam" | "user",
): RecognizedItem {
  return {
    ...item,
    media_id: mediaId,
    box,
    box_source: source,
    user_fields: mark(item, "box"),
  };
}

/** The SAM box that belongs to this card: the best overlap with its own box,
 * so several bottles in one photo stay several cards. */
export function pickSamBox(
  item: RecognizedItem,
  boxes: readonly VisibleBox[],
): VisibleBox | null {
  if (!boxes.length) return null;
  if (!item.box) return boxes.length === 1 ? boxes[0] : null;
  const ranked = [...boxes].sort(
    (a, b) => iou(item.box!, b) - iou(item.box!, a),
  );
  return iou(item.box, ranked[0]) > 0 ? ranked[0] : null;
}

export function setVisibility(
  item: RecognizedItem,
  visibility: NonNullable<RecognizedItem["visibility"]>,
): RecognizedItem {
  return { ...item, visibility, user_fields: mark(item, "visibility") };
}

export function setInstance(
  item: RecognizedItem,
  instance: NonNullable<RecognizedItem["instance"]>,
): RecognizedItem {
  return { ...item, instance, user_fields: mark(item, "instance") };
}

/** Link a card to the saved stock it backs. Only categories with build rules
 * may back a stock, and only one of the matching kind and material. */
export function linkStock(
  item: RecognizedItem,
  stock: Pick<Stock, "id" | "kind" | "material"> | null,
): RecognizedItem {
  if (stock) {
    const s = support(item.identity);
    if (s.state !== "available")
      throw new Error(`${item.name}: build rules are not available yet.`);
    if (s.kind !== stock.kind || s.material !== stock.material)
      throw new Error(
        `${item.name} cannot back a ${stock.material} ${stock.kind}.`,
      );
  }
  return {
    ...item,
    stock_id: stock?.id ?? null,
    user_fields: mark(item, "stock_id"),
  };
}

/** After an identity correction, a link that no longer fits is dropped. */
export function keepValidLink(
  item: RecognizedItem,
  stocks: readonly Pick<Stock, "id" | "kind" | "material">[],
): RecognizedItem {
  if (!item.stock_id) return item;
  const stock = stocks.find((s) => s.id === item.stock_id);
  const s = support(item.identity);
  return stock &&
    s.state === "available" &&
    s.kind === stock.kind &&
    s.material === stock.material
    ? item
    : { ...item, stock_id: null };
}
