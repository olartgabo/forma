import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CATEGORIES,
  CAPABILITY_TEXT,
  capability,
  correctIdentity,
  identityLabel,
  keepValidLink,
  linkFits,
  linkStock,
  mergeProposals,
  pickSamBox,
  renameItem,
  support,
} from "../src/components/guided-intake/recognized.ts";

const box = (x1, y1, x2, y2) => ({ x1, y1, x2, y2 });
const proposal = (identity, b = null, extra = {}) => ({
  identity,
  visible_evidence: "visible",
  box: b,
  visibility: "full",
  instance: "single",
  ...extra,
});
let counter = 0;
const newId = (name) =>
  `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}--${++counter}`;

test("the generated catalog has 48 categories, each with a capability", () => {
  assert.equal(CATEGORIES.length, 48);
  assert.equal(new Set(CATEGORIES.map((c) => c.id)).size, 48);
  for (const c of CATEGORIES) assert.ok(CAPABILITY_TEXT[c.capability], c.id);
});

test("support is separate from identity; unsupported is still a result", () => {
  assert.deepEqual(
    support({ outcome: "catalog", category_id: "food_container" }),
    {
      state: "not_available",
      reason: "Identified; build rules not available yet.",
    },
  );
  assert.equal(
    support({ outcome: "other", other_label: "ceramic mug" }).reason,
    "Identified; build rules not available yet.",
  );
  assert.match(
    support({ outcome: "uncertain", alternatives: ["felt"] }).reason,
    /Not identified yet/,
  );
  const cardboard = support({
    outcome: "catalog",
    category_id: "corrugated_cardboard",
  });
  assert.equal(cardboard.state, "available");
  assert.equal(cardboard.material, "cardboard");
  assert.equal(
    identityLabel({ outcome: "uncertain", alternatives: ["felt"] }),
    "Not sure what this is",
  );
  assert.equal(
    capability({ outcome: "catalog", category_id: "plastic_bottle" }),
    "ruler_or_more_views",
  );
  assert.equal(
    capability({ outcome: "catalog", category_id: "masking_tape" }),
    "no_quantity_from_photo",
  );
  assert.equal(capability({ outcome: "uncertain" }), null);
});

test("separate instances become separate cards; groups keep no count", () => {
  const merged = mergeProposals(
    [],
    [
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.1, 0.1, 0.3, 0.9),
      ),
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.5, 0.1, 0.7, 0.9),
        { visibility: "partial" },
      ),
      proposal({ outcome: "catalog", category_id: "paper_clips" }, null, {
        instance: "group_count_unknown",
      }),
      proposal({
        outcome: "uncertain",
        alternatives: ["felt", "fabric_scrap"],
      }),
    ],
    "photo-1",
    newId,
  );
  assert.equal(merged.added, 4);
  const names = merged.items.map((i) => i.name);
  assert.deepEqual(names, [
    "Plastic bottle",
    "Plastic bottle 2",
    "Paper clips",
    "Unknown item",
  ]);
  assert.equal(new Set(merged.items.map((i) => i.id)).size, 4);
  assert.equal(merged.items[1].visibility, "partial");
  assert.equal(merged.items[2].instance, "group_count_unknown");
  assert.equal(merged.items[3].identity.category_id, undefined);
  assert.equal(merged.items[0].box_source, "muse_approximate");
});

test("overlapping objects in one answer stay separate cards", () => {
  const merged = mergeProposals(
    [],
    [
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.1, 0.1, 0.6, 0.9),
      ),
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.2, 0.1, 0.7, 0.9),
      ),
    ],
    "photo-1",
    newId,
  );
  assert.equal(merged.added, 2);
  assert.equal(merged.skipped, 0);
  // Against one saved card, only the best overlap is absorbed.
  const later = mergeProposals(
    merged.items.slice(0, 1),
    [
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.1, 0.1, 0.6, 0.9),
      ),
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.2, 0.1, 0.7, 0.9),
      ),
    ],
    "photo-1",
    newId,
  );
  assert.equal(later.skipped, 1);
  assert.equal(later.added, 1);
});

test("matching with saved cards has maximum size, so none is duplicated", () => {
  const card = (id, x1, x2) => ({
    id,
    name: id,
    identity: { outcome: "catalog", category_id: "plastic_bottle" },
    identity_source: "user",
    media_id: "photo-1",
    box: box(x1, 0, x2, 1),
    box_source: "user",
  });
  const saved = [card("a", 0, 0.6), card("b", 0.28, 0.88)];
  const later = mergeProposals(
    saved,
    [
      proposal({ outcome: "uncertain" }, box(0.1, 0, 0.7, 1)),
      proposal({ outcome: "uncertain" }, box(0, 0, 0.4, 1)),
    ],
    "photo-1",
    newId,
  );
  assert.equal(later.added, 0);
  assert.equal(later.skipped, 2);
  assert.deepEqual(later.items, saved);
});

test("corrections survive later suggestions and a save/reload round trip", () => {
  const first = mergeProposals(
    [],
    [
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.1, 0.1, 0.3, 0.9),
      ),
    ],
    "photo-1",
    newId,
  ).items;
  const corrected = renameItem(
    correctIdentity(first[0], {
      outcome: "catalog",
      category_id: "food_container",
    }),
    "Juice jug",
  );
  const saved = JSON.parse(JSON.stringify([corrected]));
  const later = mergeProposals(
    saved,
    [
      // The same object, called something else: never overwrites the user.
      proposal(
        { outcome: "catalog", category_id: "plastic_bottle" },
        box(0.11, 0.12, 0.31, 0.88),
      ),
      proposal(
        { outcome: "catalog", category_id: "bottle_caps" },
        box(0.6, 0.6, 0.7, 0.7),
      ),
    ],
    "photo-1",
    newId,
  );
  assert.equal(later.skipped, 1);
  assert.equal(later.added, 1);
  assert.deepEqual(later.items[0], saved[0]);
  assert.equal(later.items[0].identity.category_id, "food_container");
  assert.equal(later.items[0].identity_source, "user");
  assert.deepEqual(later.items[0].user_fields, ["identity", "name"]);
  assert.equal(later.items[0].id, first[0].id);
});

test("only supported categories back a stock of the matching type", () => {
  const [bottle] = mergeProposals(
    [],
    [proposal({ outcome: "catalog", category_id: "plastic_bottle" })],
    "photo-1",
    newId,
  ).items;
  const sheet = { id: "sheet-a", kind: "sheet", material: "cardboard" };
  assert.throws(
    () => linkStock(bottle, sheet),
    /build rules are not available/,
  );
  const box1 = correctIdentity(bottle, {
    outcome: "catalog",
    category_id: "corrugated_cardboard",
  });
  const linked = linkStock(box1, sheet);
  assert.equal(linked.stock_id, "sheet-a");
  assert.throws(
    () =>
      linkStock(box1, { id: "t", kind: "tape", material: "other_supported" }),
    /cannot back/,
  );
  // A correction keeps the link but marks it as not fitting; only a missing
  // stock drops it.
  const corrected = keepValidLink(
    correctIdentity(linked, { outcome: "uncertain" }),
    [sheet],
  );
  assert.equal(corrected.stock_id, "sheet-a");
  assert.equal(linkFits(corrected, [sheet]), false);
  assert.equal(linkFits(linked, [sheet]), true);
  assert.equal(keepValidLink(linked, []).stock_id, null);
});

test("SAM boxes attach to the card they overlap, not the largest one", () => {
  const item = {
    id: "b--1",
    name: "Bottle",
    identity: { outcome: "catalog", category_id: "plastic_bottle" },
    identity_source: "muse_suggestion",
    media_id: "photo-1",
    box: box(0.5, 0.1, 0.7, 0.9),
    box_source: "muse_approximate",
  };
  const left = box(0.05, 0.05, 0.45, 0.95);
  const right = box(0.52, 0.12, 0.69, 0.88);
  assert.deepEqual(pickSamBox(item, [left, right]), right);
  assert.equal(pickSamBox(item, [box(0, 0, 0.1, 0.1)]), null);
  assert.equal(pickSamBox({ ...item, box: null }, [left, right]), null);
  assert.deepEqual(pickSamBox({ ...item, box: null }, [left]), left);
});

test("intake answers: legacy labels, no objects and partial lists", async () => {
  const { intakeNotice } =
    await import("../src/components/guided-intake/recognized.ts");
  let applied = 0;
  const apply = (proposals) => {
    applied += proposals.length;
    return { added: proposals.length, skipped: 0 };
  };
  // Live runs 1 and 2 returned labels only: never turned into cards.
  const legacy = intakeNotice(
    { labels: ["torn corrugated cardboard stack"] },
    [],
    apply,
  );
  assert.match(legacy, /did not return item cards/);
  assert.match(legacy, /Nothing was added/);
  assert.equal(applied, 0);
  assert.match(
    intakeNotice({ recognition: "no_objects", labels: [] }, [], apply),
    /found no objects/,
  );
  assert.match(
    intakeNotice({ recognition: "items", labels: ["x"] }, [], apply),
    /could not be used/,
  );
  assert.equal(applied, 0);
  const one = proposal({
    outcome: "catalog",
    category_id: "corrugated_cardboard",
  });
  const partial = intakeNotice(
    { recognition: "partial", labels: [] },
    [one],
    apply,
  );
  assert.match(partial, /Muse suggested 1 item/);
  assert.match(partial, /more objects are visible/);
  assert.equal(applied, 1);
});

test("SAM boxes for the whole photo or the reference are not materials", async () => {
  const { usableSamBoxes } =
    await import("../src/components/guided-intake/model.ts");
  const whole = { x1: 0, y1: 0, x2: 799, y2: 599 };
  const ref = { x1: 20, y1: 20, x2: 120, y2: 90 };
  const sheet = { x1: 300, y1: 200, x2: 600, y2: 450 };
  const corners = [
    { x: 18, y: 18 },
    { x: 122, y: 18 },
    { x: 122, y: 92 },
    { x: 18, y: 92 },
  ];
  assert.deepEqual(usableSamBoxes([], 800, 600), { usable: [], rejected: 0 });
  assert.deepEqual(usableSamBoxes([whole, ref], 800, 600, corners), {
    usable: [],
    rejected: 2,
  });
  assert.deepEqual(usableSamBoxes([whole, ref, sheet], 800, 600, corners), {
    usable: [sheet],
    rejected: 2,
  });
  // Without a known reference position only the whole-photo box is dropped.
  assert.deepEqual(usableSamBoxes([ref, sheet], 800, 600).usable, [ref, sheet]);
});

test("a material beside a rotated reference is not taken for it", async () => {
  const { usableSamBoxes } =
    await import("../src/components/guided-intake/model.ts");
  // Diamond-shaped card: its bounding box has empty corners.
  const diamond = [
    { x: 200, y: 0 },
    { x: 400, y: 200 },
    { x: 200, y: 400 },
    { x: 0, y: 200 },
  ];
  const corner = { x1: 0, y1: 0, x2: 80, y2: 80 };
  const onCard = { x1: 150, y1: 150, x2: 250, y2: 250 };
  assert.deepEqual(usableSamBoxes([corner, onCard], 1000, 1000, diamond), {
    usable: [corner],
    rejected: 1,
  });
});
