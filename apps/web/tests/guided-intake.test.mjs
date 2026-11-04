import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyEstimate,
  boxOutline,
  clearValue,
  defaultName,
  displayName,
  editablePoints,
  estimateSummary,
  nameFromId,
  needsReferenceValues,
  newStock,
  recordRuler,
  referenceInput,
  refusalReasons,
  renameStock,
  replaceStock,
  sizeState,
  stalePhotoValues,
  stockIdFor,
  suggestFromLabel,
} from "../src/components/guided-intake/model.ts";
import {
  EstimateRequestError,
  photoEstimates,
  validRecord,
} from "../src/lib/photo-estimates.ts";

const dims = [
  {
    name: "edge_length_mm",
    definition: "d",
    unit: "mm",
    value: 279.3,
    display_value: 280,
    display_step: 5,
    sensitivity_low: 276,
    sensitivity_high: 282,
    stock_field: "width_mm",
  },
  {
    name: "edge_width_mm",
    definition: "d",
    unit: "mm",
    value: 190.4,
    display_value: 190,
    display_step: 2,
    sensitivity_low: 188,
    sensitivity_high: 192,
    stock_field: "height_mm",
  },
];

function record(overrides = {}, estimate = {}) {
  return {
    estimate_id: "estimate-1",
    project_id: "project-1",
    created_revision_id: "inventory-1",
    status: "current",
    stale_reasons: [],
    replayed: false,
    estimate: {
      input_digest: "a".repeat(64),
      input: { stock_id: "cardboard-sheet-a--abc", media_id: "photo-1" },
      outcome: "estimate",
      dimensions: dims,
      calibration_status: "uncalibrated",
      measurement_status: "photo_estimate_unconfirmed",
      ...estimate,
    },
    ...overrides,
  };
}

test("labels map to supported materials and flag guesses", () => {
  assert.deepEqual(suggestFromLabel("Brown corrugated cardboard sheet"), {
    kind: "sheet",
    material: "cardboard",
    materialGuessed: false,
  });
  assert.equal(suggestFromLabel("roll of masking tape").kind, "tape");
  assert.equal(suggestFromLabel("cereal box panel").material, "paperboard");
  assert.equal(suggestFromLabel("thin strip of card stock").kind, "strip");
  assert.equal(suggestFromLabel("mystery panel").materialGuessed, true);
});

test("names are readable, unique and survive in stable IDs", () => {
  const sheet = { kind: "sheet", material: "cardboard" };
  assert.equal(defaultName(sheet, []), "Cardboard sheet A");
  assert.equal(defaultName(sheet, ["Cardboard sheet A"]), "Cardboard sheet B");
  assert.equal(
    defaultName({ kind: "tape", material: "other_supported" }, []),
    "Tape roll",
  );
  const id = stockIdFor("Cardboard sheet B", "1f2e3d4c-aaaa");
  assert.match(id, /^[A-Za-z][A-Za-z0-9_-]{0,95}$/);
  assert.equal(nameFromId(id), "Cardboard sheet B");
  assert.equal(nameFromId("stock-123"), "Material");
  assert.match(stockIdFor("  ", "abc"), /^[A-Za-z]/);
});

test("using an estimate never confirms it; a ruler value is a separate action", () => {
  const stock = newStock(
    "cardboard-sheet-a--abc",
    suggestFromLabel("cardboard"),
    null,
  );
  const explored = applyEstimate(stock, record());
  assert.deepEqual(explored.width_mm, {
    value: 280,
    unit: "mm",
    source: "photo_estimate",
    confirmed: false,
  });
  assert.deepEqual(explored.image_ids, ["photo-1"]);
  assert.equal(sizeState(explored.width_mm).state, "photo");
  const measured = recordRuler(explored, "width_mm", 281);
  assert.deepEqual(measured.width_mm, {
    value: 281,
    unit: "mm",
    source: "user_ruler",
    confirmed: true,
  });
  assert.equal(sizeState(measured.width_mm).state, "measured");
  assert.equal(
    sizeState(clearValue(measured, "width_mm").width_mm).state,
    "unknown",
  );
  assert.throws(() => recordRuler(stock, "width_mm", 0));
});

test("stale, foreign or enclosing-only estimates cannot fill sizes", () => {
  const stock = newStock(
    "cardboard-sheet-a--abc",
    suggestFromLabel("cardboard"),
    null,
  );
  assert.throws(
    () => applyEstimate(stock, record({ status: "stale" })),
    /out of date/,
  );
  assert.throws(
    () => applyEstimate({ ...stock, id: "other--x" }, record()),
    /another material/,
  );
  const enclosing = record(
    {},
    {
      outcome: "enclosing_only",
      dimensions: dims.map((d) => ({ ...d, stock_field: null })),
    },
  );
  assert.throws(() => applyEstimate(stock, enclosing), /cannot fill/);
});

test("saved photo values are flagged when no current estimate matches", () => {
  const stock = applyEstimate(
    newStock(
      "cardboard-sheet-a--abc",
      suggestFromLabel("cardboard"),
      "photo-1",
    ),
    record(),
  );
  assert.deepEqual(stalePhotoValues(stock, [record()]), []);
  assert.deepEqual(stalePhotoValues(stock, [record({ status: "stale" })]), [
    "width_mm",
    "height_mm",
  ]);
});

test("rename keeps the stable ID, photo links and estimate through save and reload", () => {
  const id = stockIdFor("Cardboard sheet A", "1f2e3d4c-aaaa");
  const estimate = record({}, { input: { stock_id: id, media_id: "photo-1" } });
  const estimated = applyEstimate(
    newStock(id, suggestFromLabel("cardboard"), "photo-1", "Cardboard sheet A"),
    estimate,
  );
  const renamed = renameStock(estimated, "  Big lid  ");
  assert.equal(renamed.id, id);
  assert.equal(displayName(renamed), "Big lid");
  assert.deepEqual(renamed.image_ids, ["photo-1"]);
  assert.deepEqual(renamed.width_mm, estimated.width_mm);
  // Save and reload: the inventory is stored and returned as JSON.
  const reloaded = JSON.parse(JSON.stringify({ stocks: [renamed] })).stocks[0];
  assert.equal(reloaded.id, id);
  assert.equal(displayName(reloaded), "Big lid");
  assert.equal(reloaded.width_mm.source, "photo_estimate");
  assert.equal(reloaded.width_mm.confirmed, false);
  assert.deepEqual(stalePhotoValues(reloaded, [estimate]), []);
  // A stock saved before names existed still shows the name from its ID.
  const { name: _name, ...legacy } = reloaded;
  assert.equal(displayName(legacy), "Cardboard sheet A");
  assert.equal(renameStock(reloaded, "Big lid"), reloaded);
  assert.equal(displayName(renameStock(reloaded, "   ")), "Material");
});

test("a different piece gets a new ID and drops photo values and links", () => {
  const id = stockIdFor("Cardboard sheet A", "1f2e3d4c-aaaa");
  const estimate = record({}, { input: { stock_id: id, media_id: "photo-1" } });
  const measured = recordRuler(
    applyEstimate(
      newStock(id, suggestFromLabel("cardboard"), "photo-1", "Lid"),
      estimate,
    ),
    "thickness_mm",
    4,
  );
  const other = replaceStock(measured, "99aa88bb-cccc");
  assert.notEqual(other.id, id);
  assert.equal(displayName(other), "Lid");
  assert.deepEqual(other.image_ids, []);
  for (const field of ["width_mm", "height_mm", "thickness_mm"])
    assert.equal(other[field].source, "unknown");
  assert.throws(() => applyEstimate(other, estimate), /another material/);
});

test("reference input requires the printed check or a known size", () => {
  assert.throws(
    () => referenceInput({ kind: "forma_card", lineA: "", lineB: "" }),
    /Line A/,
  );
  assert.deepEqual(
    referenceInput({ kind: "forma_card", lineA: "149,5", lineB: "" }),
    {
      kind: "forma_card",
      printed_check_x_mm: 149.5,
      printed_check_y_mm: null,
      size_tolerance_mm: 0.5,
      corners_px: [],
    },
  );
  assert.throws(
    () =>
      referenceInput({
        kind: "rectangle",
        width: "100",
        height: "50",
        corners: [],
      }),
    /four reference corners/,
  );
  assert.throws(() =>
    referenceInput({ kind: "aruco_marker", side: "40", markerId: "60" }),
  );
});

test("boxes, outlines and summaries", () => {
  assert.deepEqual(
    boxOutline({ x1: 50, y1: 40, x2: 10, y2: 5 }, "manual_box"),
    {
      source: "manual_box",
      x1: 10,
      y1: 5,
      x2: 50,
      y2: 40,
      polygon_px: [],
      holes_px: [],
    },
  );
  assert.throws(() => boxOutline({ x1: 1, y1: 1, x2: 2, y2: 2 }, "manual_box"));
  const many = Array.from({ length: 500 }, (_, i) => ({ x: i, y: i }));
  assert.equal(editablePoints(many).length, 48);
  assert.equal(estimateSummary(record().estimate), "280 × 190 mm (±5 mm)");
  assert.equal(
    estimateSummary({ outcome: "needs_better_photo", dimensions: [] }),
    null,
  );
});

test("refused estimates expose their blocking reason and whether the reference is at fault", () => {
  const scale = {
    outcome: "reference_unverified",
    diagnostics: [
      { code: "reference_partial", severity: "warning", message: "W" },
      {
        code: "reference_unverified",
        severity: "blocking",
        message:
          "The measured check lines differ from the card by more than 15 %; re-measure them.",
      },
    ],
  };
  assert.deepEqual(refusalReasons(scale), [
    "The measured check lines differ from the card by more than 15 %; re-measure them.",
  ]);
  assert.equal(needsReferenceValues(scale), true);
  // A missing card needs a new photo, not different numbers.
  const missing = {
    outcome: "reference_not_found",
    diagnostics: [
      {
        code: "reference_not_found",
        severity: "blocking",
        message: "No FORMA card marker was found.",
      },
    ],
  };
  assert.deepEqual(refusalReasons(missing), [
    "No FORMA card marker was found.",
  ]);
  assert.equal(needsReferenceValues(missing), false);
  assert.deepEqual(refusalReasons(record().estimate), []);
});

test("client validates estimate records and keeps exact retries for unknown outcomes", async () => {
  assert.equal(validRecord(record(), "project-1"), true);
  assert.equal(validRecord(record(), "project-2"), false);
  assert.equal(
    validRecord(record({}, { measurement_status: "confirmed" }), "project-1"),
    false,
  );
  // Enclosing-only records that try to fill a stock field are rejected.
  assert.equal(
    validRecord(record({}, { outcome: "enclosing_only" }), "project-1"),
    false,
  );
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    if (calls.length === 1) throw new TypeError("network");
    if (calls.length === 2)
      return new Response(
        JSON.stringify({ code: "blocked", message: "busy" }),
        { status: 429 },
      );
    if (calls.length === 3)
      return new Response(
        JSON.stringify({
          code: "stale_version",
          message: "Inventory changed; reload it",
        }),
        { status: 409 },
      );
    return new Response(JSON.stringify(record()), { status: 200 });
  };
  const api = photoEstimates("token-1", "project-1");
  const body = { idempotency_key: "k-12345678" };
  await assert.rejects(
    api.create(body),
    (e) => e instanceof EstimateRequestError && e.retryExact,
  );
  await assert.rejects(
    api.create(body),
    (e) => e.retryExact && e.status === 429,
  );
  await assert.rejects(
    api.create(body),
    (e) => !e.retryExact && e.status === 409,
  );
  assert.equal((await api.create(body)).estimate_id, "estimate-1");
  assert.ok(calls.every(([, init]) => init.body === JSON.stringify(body)));
  assert.ok(calls.every(([, init]) => init.credentials === "omit"));
});
