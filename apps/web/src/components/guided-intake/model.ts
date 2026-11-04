// Pure guided-intake rules (#177). No network, storage or React here.
import type {
  Measurement,
  OutlineInput,
  PhotoEstimate,
  ReferenceInput,
  Stock,
} from "../../lib/generated/contracts";
import type { PhotoEstimateRecord } from "../../lib/generated/api-contracts";

export type Kind = Stock["kind"];
export type Material = Stock["material"];

export type Suggestion = {
  kind: Kind;
  material: Material;
  // True when the label did not name a supported material clearly.
  materialGuessed: boolean;
};

/** Map a Muse label to a supported stock kind and material. */
export function suggestFromLabel(label: string): Suggestion {
  const text = label.toLowerCase();
  if (/\btape\b/.test(text))
    return {
      kind: "tape",
      material: "other_supported",
      materialGuessed: false,
    };
  if (/\b(cord|string|twine|yarn|rope)\b/.test(text))
    return {
      kind: "cord",
      material: "other_supported",
      materialGuessed: false,
    };
  const kind: Kind = /\bstrip\b/.test(text) ? "strip" : "sheet";
  if (
    /(paperboard|cereal|card ?stock|folder|poster ?board|chipboard)/.test(text)
  )
    return { kind, material: "paperboard", materialGuessed: false };
  if (/(cardboard|corrugated|\bbox\b|carton)/.test(text))
    return { kind, material: "cardboard", materialGuessed: false };
  return { kind, material: "cardboard", materialGuessed: true };
}

const KIND_WORD: Record<Kind, string> = {
  sheet: "sheet",
  strip: "strip",
  tape: "roll",
  cord: "cord",
};
const MATERIAL_WORD: Record<Material, string> = {
  cardboard: "Cardboard",
  paperboard: "Paperboard",
  other_supported: "",
};

/** "Cardboard sheet A", "Tape roll", skipping names already in use. */
export function defaultName(
  suggestion: Pick<Suggestion, "kind" | "material">,
  taken: readonly string[],
): string {
  const base =
    suggestion.kind === "tape"
      ? "Tape roll"
      : suggestion.kind === "cord"
        ? "Cord"
        : `${MATERIAL_WORD[suggestion.material] || "Material"} ${KIND_WORD[suggestion.kind]}`;
  const used = new Set(taken.map((name) => name.toLowerCase()));
  if (suggestion.kind === "tape" || suggestion.kind === "cord")
    if (!used.has(base.toLowerCase())) return base;
  for (let i = 0; i < 26; i += 1) {
    const name = `${base} ${String.fromCharCode(65 + i)}`;
    if (!used.has(name.toLowerCase())) return name;
  }
  return `${base} ${taken.length + 1}`;
}

const ID = /^[A-Za-z][A-Za-z0-9_-]{0,95}$/;

/** A stable ID that carries the readable name, so names survive reloads. */
export function stockIdFor(name: string, random: string): string {
  const slug = name
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  const suffix = random
    .replace(/[^a-z0-9]/gi, "")
    .slice(0, 8)
    .toLowerCase();
  const id = `${/^[a-z]/.test(slug) ? slug : "material-" + slug}--${suffix}`;
  return ID.test(id) ? id : `material--${suffix}`;
}

/** The readable name encoded in an ID, or a neutral fallback. */
export function nameFromId(id: string): string {
  const [slug] = id.split("--");
  if (!slug || slug === id) return "Material";
  const words = slug.split("-").filter(Boolean);
  if (!words.length) return "Material";
  return words
    .map((word, index) =>
      index === 0
        ? word[0].toUpperCase() + word.slice(1)
        : word.length === 1
          ? word.toUpperCase()
          : word,
    )
    .join(" ");
}

export function unknownMeasurement(): Measurement {
  return { value: null, unit: "mm", source: "unknown", confirmed: false };
}

export function newStock(
  id: string,
  suggestion: Suggestion,
  mediaId: string | null,
): Stock {
  return {
    id,
    kind: suggestion.kind,
    material: suggestion.material,
    condition: "uncertain",
    width_mm: unknownMeasurement(),
    height_mm: unknownMeasurement(),
    thickness_mm: unknownMeasurement(),
    remaining_length_mm: unknownMeasurement(),
    usable_regions: [],
    image_ids: mediaId ? [mediaId] : [],
  };
}

export type SizeField = "width_mm" | "height_mm";

/** Values a current estimate may prefill; never confirmed. */
export function prefill(estimate: PhotoEstimate) {
  const values: Partial<Record<SizeField, number>> = {};
  for (const d of estimate.dimensions ?? [])
    if (d.stock_field) values[d.stock_field] = d.display_value;
  return values;
}

/** "Use photo estimate for exploring": unconfirmed photo_estimate values. */
export function applyEstimate(
  stock: Stock,
  record: PhotoEstimateRecord,
): Stock {
  if (record.status !== "current")
    throw new Error("This estimate is out of date. Measure again.");
  if (record.estimate.input.stock_id !== stock.id)
    throw new Error("This estimate belongs to another material.");
  const values = prefill(record.estimate);
  if (values.width_mm === undefined || values.height_mm === undefined)
    throw new Error("This estimate cannot fill in a size.");
  const media = record.estimate.input.media_id;
  return {
    ...stock,
    image_ids: stock.image_ids?.includes(media)
      ? stock.image_ids
      : [...(stock.image_ids ?? []), media],
    width_mm: photoMeasurement(values.width_mm),
    height_mm: photoMeasurement(values.height_mm),
  };
}

function photoMeasurement(value: number): Measurement {
  return { value, unit: "mm", source: "photo_estimate", confirmed: false };
}

/** "I measured it": a ruler value is a separate, confirmed action. */
export function recordRuler(
  stock: Stock,
  field: SizeField | "thickness_mm" | "remaining_length_mm",
  value: number,
): Stock {
  if (!Number.isFinite(value) || value <= 0)
    throw new Error("Enter a size greater than zero in millimetres.");
  return {
    ...stock,
    [field]: { value, unit: "mm", source: "user_ruler", confirmed: true },
  };
}

/** "I don't know": clears the value back to unknown. */
export function clearValue(stock: Stock, field: SizeField): Stock {
  return { ...stock, [field]: unknownMeasurement() };
}

export type SizeState =
  | { state: "unknown" }
  | { state: "photo"; value: number }
  | { state: "measured"; value: number }
  | { state: "other"; value: number | null; source: string };

export function sizeState(measurement: Measurement): SizeState {
  if (measurement.value === null || measurement.value === undefined)
    return { state: "unknown" };
  if (measurement.source === "photo_estimate")
    return { state: "photo", value: measurement.value };
  if (measurement.confirmed && measurement.source === "user_ruler")
    return { state: "measured", value: measurement.value };
  return {
    state: "other",
    value: measurement.value,
    source: measurement.source,
  };
}

/** Saved photo values that no longer match a current estimate. */
export function stalePhotoValues(
  stock: Stock,
  records: readonly PhotoEstimateRecord[],
): SizeField[] {
  const current = records.filter(
    (r) => r.status === "current" && r.estimate.input.stock_id === stock.id,
  );
  return (["width_mm", "height_mm"] as const).filter((field) => {
    const m = stock[field];
    if (m.source !== "photo_estimate") return false;
    return !current.some((r) =>
      (r.estimate.dimensions ?? []).some(
        (d) => d.stock_field === field && d.display_value === m.value,
      ),
    );
  });
}

export function latestRecord(
  records: readonly PhotoEstimateRecord[],
  stockId: string,
): PhotoEstimateRecord | null {
  const mine = records.filter((r) => r.estimate.input.stock_id === stockId);
  return mine.length ? mine[mine.length - 1] : null;
}

export type ReferenceDraft =
  | { kind: "forma_card"; lineA: string; lineB: string }
  | { kind: "aruco_marker"; side: string; markerId: string }
  | { kind: "rectangle"; width: string; height: string; corners: Point[] };
export type Point = { x: number; y: number };

function positive(raw: string, label: string, max = 2000): number {
  const value = Number(raw.replace(",", "."));
  if (!raw.trim() || !Number.isFinite(value) || value <= 0 || value > max)
    throw new Error(
      `${label} must be a number of millimetres greater than zero.`,
    );
  return value;
}

/** Build the reference input, or explain the one missing fact. */
export function referenceInput(draft: ReferenceDraft): ReferenceInput {
  if (draft.kind === "forma_card") {
    const a = positive(draft.lineA, "Line A", 400);
    const b = draft.lineB.trim() ? positive(draft.lineB, "Line B", 400) : null;
    // A ruler read to the nearest millimetre is within half a millimetre.
    return {
      kind: "forma_card",
      printed_check_x_mm: a,
      printed_check_y_mm: b,
      size_tolerance_mm: 0.5,
      corners_px: [],
    };
  }
  if (draft.kind === "aruco_marker") {
    const side = positive(draft.side, "Marker side");
    const id = Number(draft.markerId);
    if (!Number.isInteger(id) || id < 0 || id > 49)
      throw new Error("Marker ID must be a whole number from 0 to 49.");
    return {
      kind: "aruco_marker",
      width_mm: side,
      height_mm: side,
      size_source: "ruler",
      size_tolerance_mm: 0.5,
      aruco_id: id,
      corners_px: [],
    };
  }
  const width = positive(draft.width, "Reference width");
  const height = positive(draft.height, "Reference height");
  if (draft.corners.length !== 4)
    throw new Error(
      "Place all four reference corners, starting at one end of the width.",
    );
  return {
    kind: "rectangle",
    width_mm: width,
    height_mm: height,
    size_source: "ruler",
    size_tolerance_mm: 0.5,
    corners_px: draft.corners,
  };
}

export type Box = { x1: number; y1: number; x2: number; y2: number };

export function boxOutline(
  box: Box,
  source: "sam_box" | "manual_box",
): OutlineInput {
  const x1 = Math.round(Math.min(box.x1, box.x2));
  const x2 = Math.round(Math.max(box.x1, box.x2));
  const y1 = Math.round(Math.min(box.y1, box.y2));
  const y2 = Math.round(Math.max(box.y1, box.y2));
  if (x2 - x1 < 4 || y2 - y1 < 4)
    throw new Error("Draw a larger box around the material.");
  return { source, x1, y1, x2, y2, polygon_px: [], holes_px: [] };
}

/** Reduce a refined outline to at most `limit` editable points. */
export function editablePoints(points: readonly Point[], limit = 48): Point[] {
  if (points.length <= limit) return points.map((p) => ({ ...p }));
  const step = points.length / limit;
  return Array.from({ length: limit }, (_, i) => ({
    ...points[Math.floor(i * step)],
  }));
}

export function polygonOutline(points: readonly Point[]): OutlineInput {
  if (points.length < 3)
    throw new Error("An outline needs at least three points.");
  return {
    source: "user_polygon",
    polygon_px: points.map((p) => ({ ...p })),
    holes_px: [],
  };
}

/** Plain-language summary shown on a card; no unjustified decimals. */
export function estimateSummary(estimate: PhotoEstimate): string | null {
  const d = Object.fromEntries(
    (estimate.dimensions ?? []).map((x) => [x.name, x]),
  );
  const fmt = (x: { display_value: number; display_step: number }) =>
    `${x.display_value.toFixed(x.display_step < 1 ? 1 : 0)}`;
  if (estimate.outcome === "estimate" && d.edge_length_mm && d.edge_width_mm)
    return `${fmt(d.edge_length_mm)} × ${fmt(d.edge_width_mm)} mm (±${d.edge_length_mm.display_step} mm)`;
  if (
    estimate.outcome === "enclosing_only" &&
    d.enclosing_length_mm &&
    d.enclosing_width_mm
  )
    return `Fits within ${fmt(d.enclosing_length_mm)} × ${fmt(d.enclosing_width_mm)} mm (not all usable)`;
  return null;
}

export function sizeFieldsFor(kind: Kind): SizeField[] {
  return kind === "tape" || kind === "cord" ? [] : ["width_mm", "height_mm"];
}
