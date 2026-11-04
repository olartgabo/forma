// Measurement-decision client checks on labeled SYNTHETIC responses; no physical pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  answerBody,
  answerReceipts,
  baselineAfterSave,
  baselineForAnswer,
  baselineForStand,
  baselineReceipts,
  measurementApi,
  validateChange,
  validateDecision,
} from "../src/components/active-measurement/client.ts";

const hash = (c) => c.repeat(64);
const unknown = {
  value: null,
  unit: "mm",
  source: "unknown",
  confirmed: false,
};
const sheet = {
  id: "sheet-a",
  kind: "sheet",
  material: "cardboard",
  condition: "usable",
  width_mm: unknown,
  height_mm: unknown,
  thickness_mm: { value: 2, unit: "mm", source: "user_ruler", confirmed: true },
  remaining_length_mm: unknown,
  usable_regions: [],
  image_ids: [],
};
const tape = {
  ...sheet,
  id: "tape-a",
  kind: "tape",
  width_mm: { value: 30, unit: "mm", source: "user_ruler", confirmed: true },
};
const project = {
  id: "project-a",
  goal: "SYNTHETIC",
  revision_id: "inventory-a",
  active_version_id: null,
  stocks: [sheet, tape],
  inventory_confirmed: true,
  requirements: {
    tools: ["SYNTHETIC ruler"],
    constraints: {
      device_mass_g: {
        value: null,
        unit: "g",
        source: "unknown",
        confirmed: false,
      },
    },
  },
};
function question(overrides = {}) {
  return {
    question_id: hash("b"),
    target: {
      key: "stock:sheet-a:width_mm",
      kind: "stock",
      property: "width_mm",
      stock_id: "sheet-a",
      label: "Width of sheet sheet-a",
      pieces: [],
    },
    unit: "mm",
    method: "SYNTHETIC ruler",
    where: "Sheet sheet-a",
    current: unknown,
    threshold: {
      comparison: "at_least",
      lower: 78,
      upper: null,
      unit: "mm",
      basis: "SYNTHETIC",
    },
    required_precision: 1,
    precision_basis: "SYNTHETIC",
    affected_candidate_ids: [],
    affected_case_ids: [],
    why: "SYNTHETIC",
    capture: "inventory",
    ...overrides,
  };
}
function decision(overrides = {}) {
  return {
    decision_id: hash("a"),
    identity: {
      project_id: "project-a",
      inventory_revision_id: "inventory-a",
      active_version_id: null,
      last_event_id: null,
      context_fingerprint: hash("0"),
      measurement_record_ids: [],
      declined_target_keys: [],
      rule_version: "measurement-decision-v1",
    },
    outcome: "question",
    question: question(),
    pending_questions: 1,
    reasons: ["SYNTHETIC"],
    missing_capabilities: [],
    facts: [],
    design: null,
    stability: null,
    invalidated: [],
    selection_rule: "SYNTHETIC rule",
    physical_verification: "not_attempted",
    ...overrides,
  };
}

test("decisions are validated field by field", () => {
  assert.equal(validateDecision(decision(), "project-a").outcome, "question");
  assert.throws(() => validateDecision(decision(), "project-b"));
  assert.throws(() =>
    validateDecision(decision({ question: null }), "project-a"),
  );
  assert.throws(() =>
    validateDecision(
      decision({ outcome: "none_needed", question: question() }),
      "project-a",
    ),
  );
  assert.throws(() =>
    validateDecision(decision({ question: question({ why: 3 }) }), "project-a"),
  );
  assert.throws(
    () =>
      validateDecision(
        decision({ physical_verification: "passed" }),
        "project-a",
      ),
    (e) => e.retry === true,
  );
  assert.throws(() =>
    validateChange(
      { before_decision_id: hash("a"), after_decision_id: hash("c") },
      "project-a",
    ),
  );
});

test("an answer changes only its target and is confirmed by the user", () => {
  const body = answerBody(project, question(), 200, "answer-0001");
  assert.equal(body.expected_revision_id, "inventory-a");
  assert.deepEqual(body.stocks[0].width_mm, {
    value: 200,
    unit: "mm",
    source: "user_ruler",
    confirmed: true,
  });
  assert.deepEqual(body.stocks[0].height_mm, unknown);
  assert.deepEqual(body.stocks[1], tape);
  assert.equal("requirements" in body, false);
  assert.throws(() =>
    answerBody(project, question(), Number.NaN, "answer-0002"),
  );
  assert.throws(() => answerBody(project, question(), 0, "answer-0003"));
});

test("usable area needs confirmed dimensions and becomes one whole region", () => {
  const region = question({
    target: {
      key: "stock:sheet-a:usable_region",
      kind: "stock",
      property: "usable_region",
      stock_id: "sheet-a",
      label: "Usable area",
      pieces: [],
    },
  });
  assert.throws(() => answerBody(project, region, null, "answer-0004"));
  const sized = {
    ...project,
    stocks: [
      {
        ...sheet,
        width_mm: {
          value: 200,
          unit: "mm",
          source: "user_ruler",
          confirmed: true,
        },
        height_mm: {
          value: 550,
          unit: "mm",
          source: "user_ruler",
          confirmed: true,
        },
      },
      tape,
    ],
  };
  const body = answerBody(sized, region, null, "answer-0005");
  assert.deepEqual(body.stocks[0].usable_regions, [
    {
      id: "sheet-a",
      geometry: { x: 0, y: 0, width: 200, height: 550, rotation_deg: 0 },
    },
  ]);
});

test("usable area accepts a stock ID at the domain length limit", () => {
  const stockId = "s".repeat(96);
  const sized = {
    ...project,
    stocks: [
      {
        ...sheet,
        id: stockId,
        width_mm: {
          value: 200,
          unit: "mm",
          source: "user_ruler",
          confirmed: true,
        },
        height_mm: {
          value: 550,
          unit: "mm",
          source: "user_ruler",
          confirmed: true,
        },
      },
    ],
  };
  const region = question({
    target: {
      key: `stock:${stockId}:usable_region`,
      kind: "stock",
      property: "usable_region",
      stock_id: stockId,
      label: "Usable area",
      pieces: [],
    },
  });
  const body = answerBody(sized, region, null, "answer-long-id");
  const saved = body.stocks[0].usable_regions[0];
  assert.match(saved.id, /^[A-Za-z][A-Za-z0-9_-]{0,95}$/);
  assert.equal(body.stocks[0].id, stockId);
  assert.deepEqual(saved.geometry, {
    x: 0,
    y: 0,
    width: 200,
    height: 550,
    rotation_deg: 0,
  });
});

test("a requirement answer updates only that constraint", () => {
  const mass = question({
    target: {
      key: "requirement:constraints:device_mass_g",
      kind: "requirement",
      property: "device_mass_g",
      label: "Device mass",
      pieces: [],
    },
    unit: "g",
    capture: "requirements",
  });
  const body = answerBody(project, mass, 180, "answer-0006");
  assert.deepEqual(body.requirements.constraints.device_mass_g, {
    value: 180,
    unit: "g",
    source: "user_ruler",
    confirmed: true,
  });
  assert.deepEqual(body.requirements.tools, ["SYNTHETIC ruler"]);
  assert.deepEqual(body.stocks, project.stocks);
});

class MemoryStorage {
  values = new Map();
  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    this.values.set(key, String(value));
  }
  removeItem(key) {
    this.values.delete(key);
  }
}

test("answer and baseline receipts survive reload independently", async () => {
  const storage = new MemoryStorage();
  const body = answerBody(project, question(), 200, "answer-0007");
  await answerReceipts.retain("token-a", "project-a", body, storage);
  await baselineReceipts.retain(
    "token-a",
    "project-a",
    { decision: decision(), state: "saved" },
    storage,
  );
  assert.deepEqual(
    await answerReceipts.pending("token-a", "project-a", storage),
    body,
  );
  const answerKey = [...storage.values.keys()].find((k) =>
    k.startsWith("forma-measurement-answer"),
  );
  storage.setItem(answerKey, "{corrupt");
  await assert.rejects(answerReceipts.pending("token-a", "project-a", storage));
  assert.equal(
    (await baselineReceipts.pending("token-a", "project-a", storage)).decision
      .decision_id,
    hash("a"),
  );
  await answerReceipts.discard("token-a", "project-a", storage);
  assert.notEqual(
    await baselineReceipts.pending("token-a", "project-a", storage),
    null,
  );
});

test("baseline replacement preserves the earlier decision when storage fails", async () => {
  const storage = new MemoryStorage();
  const before = { decision: decision(), state: "sending" };
  const after = { ...before, state: "saved" };
  await baselineReceipts.retain("token-a", "project-a", before, storage);
  await assert.rejects(
    baselineReceipts.retain("token-a", "project-a", after, storage),
    /unresolved/,
  );
  const setItem = storage.setItem;
  storage.setItem = () => {
    throw new Error("storage full");
  };
  await assert.rejects(
    baselineReceipts.replace("token-a", "project-a", after, storage),
    /storage full/,
  );
  assert.deepEqual(
    await baselineReceipts.pending("token-a", "project-a", storage),
    before,
  );
  storage.setItem = setItem;
  await baselineReceipts.replace("token-a", "project-a", after, storage);
  assert.deepEqual(
    await baselineReceipts.pending("token-a", "project-a", storage),
    after,
  );
  const [key] = storage.values.keys();
  storage.setItem(key, "{corrupt");
  await assert.rejects(
    baselineReceipts.replace("token-a", "project-a", before, storage),
    /cannot be verified/,
  );
  assert.equal(storage.getItem(key), "{corrupt");
});

function respond(status, body) {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
}

test("inventory saves keep the key on ambiguous outcomes", async () => {
  const original = globalThis.fetch;
  const api = measurementApi("token", "project-a");
  const signal = new AbortController().signal;
  const body = answerBody(project, question(), 200, "answer-0008");
  try {
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(api.saveInventory(body, signal), (e) => e.retry);
    globalThis.fetch = respond(200, { project: { id: "project-a" } });
    await assert.rejects(api.saveInventory(body, signal), (e) => e.retry);
    globalThis.fetch = respond(409, { code: "stale_version", message: "x" });
    await assert.rejects(
      api.saveInventory(body, signal),
      (e) => !e.retry && e.stale,
    );
    const sent = [];
    globalThis.fetch = async (url, init) => {
      sent.push([url, init.method, JSON.parse(init.body)]);
      return new Response(
        JSON.stringify({ project: { ...project, revision_id: "inventory-b" } }),
      );
    };
    await api.saveInventory(body, signal);
    assert.deepEqual(sent[0].slice(0, 2), [
      "/api/projects/project-a/inventory",
      "PUT",
    ]);
    assert.equal(sent[0][2].idempotency_key, "answer-0008");
  } finally {
    globalThis.fetch = original;
  }
});

test("rendered units and comparisons are checked against the contract", () => {
  const bad = [
    question({ unit: { mm: true } }),
    question({ unit: "inch" }),
    question({ current: { ...unknown, unit: { value: "mm" } } }),
    question({
      threshold: { ...question().threshold, unit: ["mm"] },
    }),
    question({
      threshold: { ...question().threshold, comparison: { at_least: 1 } },
    }),
  ];
  for (const q of bad)
    assert.throws(
      () => validateDecision(decision({ question: q }), "project-a"),
      (e) => e.retry === true,
    );
});

test("a refused answer is never shown as saved", () => {
  const before = decision();
  const sending = baselineForAnswer(null, before);
  assert.deepEqual(sending, { decision: before, state: "sending" });
  // A definite refusal saved nothing and drops the comparison point.
  assert.equal(baselineAfterSave(sending, false), null);
  const saved = baselineAfterSave(sending, true);
  assert.equal(saved.state, "saved");
  // A second answer keeps the first saved comparison point, and refusing
  // the second does not undo the first.
  const next = decision({ decision_id: hash("c") });
  assert.equal(baselineForAnswer(saved, next), saved);
  assert.equal(baselineAfterSave(saved, false), saved);
  // A retry after reload without a kept comparison point still works.
  assert.equal(baselineForAnswer(null, null), null);
  assert.equal(baselineAfterSave(null, true), null);
});

test("a built-stand question is kept as the comparison point", () => {
  const stand = decision({
    question: question({
      target: {
        key: "assembled_stand:version-a:assembled_stand",
        kind: "assembled_stand",
        property: "assembled_stand",
        label: "Assembled stand",
        pieces: [],
      },
      unit: "batch",
      threshold: null,
      capture: "stability_measurements",
    }),
  });
  assert.deepEqual(baselineForStand(null, stand), {
    decision: stand,
    state: "external",
  });
  // An inventory answer's comparison point is not replaced.
  const saved = { decision: decision(), state: "saved" };
  assert.equal(baselineForStand(saved, stand), saved);
  assert.equal(baselineForStand(null, decision()), null);
});

test("design settings notes are validated before they are shown", () => {
  const notes = ["SYNTHETIC settings reviewed for inventory-a are used."];
  assert.deepEqual(
    validateDecision(decision({ settings: notes }), "project-a").settings,
    notes,
  );
  assert.throws(
    () => validateDecision(decision({ settings: [{ note: 1 }] }), "project-a"),
    (e) => e.retry === true,
  );
});
