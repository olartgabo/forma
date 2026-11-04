// Design-search client checks on labeled SYNTHETIC responses; no physical pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SynthesisRequestError,
  domainValues,
  museReceipts,
  selectionBody,
  selectionReceipts,
  validSelectRequest,
  validateMuse,
  synthesisApi,
  validateProbe,
  validateSearch,
  validateSelection,
} from "../src/components/design-candidates/client.ts";

const context = {
  projectId: "project-a",
  inventoryRevisionId: "inventory-a",
  activeVersionId: null,
  lastEventId: null,
};
const searchId = "a".repeat(64);
const identity = {
  project_id: "project-a",
  inventory_revision_id: "inventory-a",
  active_version_id: null,
  last_event_id: null,
  context_fingerprint: "0".repeat(64),
  measurement_record_ids: [],
  engine_version: "stand-synthesis-v1",
};
const design = {
  family: "triangular-tape-stand-v1",
  sheet_stock_id: "sheet-a",
  tape_stock_id: "tape-a",
  tape_profile_id: "tape-profile",
  fold_profile_id: "fold-profile",
  part_width_mm: 70,
  support_length_mm: 100,
  footprint_depth_mm: 55,
  lip_mm: 15,
  support_angle_deg: 60,
};
function candidate(overrides = {}) {
  return {
    candidate_id: "cand-0123456789abcdef",
    design,
    status: "acceptable",
    pieces: [],
    material: null,
    checks: [
      {
        check_id: "compiler",
        category: "compiler",
        status: "modeled_pass",
        detail: "SYNTHETIC",
        blocker_codes: [],
      },
      {
        check_id: "stability-tip-portrait",
        category: "stability",
        case_id: "portrait",
        status: "missing_input",
        detail: "SYNTHETIC",
        blocker_codes: [],
      },
    ],
    construction: [],
    unresolved: ["stability-tip-portrait: missing input"],
    blockers: [],
    ...overrides,
  };
}
function result(overrides = {}) {
  return {
    search_id: searchId,
    identity,
    status: "candidates_found",
    budget: { max_nodes: 192, max_seconds: 5 },
    exhausted: null,
    nodes_evaluated: 64,
    nodes_total: 64,
    domains: [
      {
        sheet_stock_id: "sheet-a",
        parameter: "footprint_depth_mm",
        unit: "mm",
        step_mm: 35,
        lower_mm: 55,
        upper_mm: 160,
        count: 4,
        lower_basis: "SYNTHETIC",
        upper_basis: "SYNTHETIC",
        empty_reason: null,
      },
    ],
    candidates: [candidate()],
    rejections: [],
    blockers: [],
    ranking: "SYNTHETIC",
    limitations: ["SYNTHETIC"],
    physical_verification: "not_attempted",
    ...overrides,
  };
}

test("accepts a coherent search and lists its finite domain", () => {
  const value = validateSearch(result(), context);
  assert.equal(value.candidates.length, 1);
  assert.deepEqual(
    domainValues(value, "sheet-a", "footprint_depth_mm"),
    [55, 90, 125, 160],
  );
  assert.deepEqual(domainValues(value, "sheet-b", "footprint_depth_mm"), []);
});

test("rejects foreign identities, extra candidates and hidden failures", () => {
  assert.throws(() =>
    validateSearch(
      result({ identity: { ...identity, project_id: "other" } }),
      context,
    ),
  );
  assert.throws(() =>
    validateSearch(
      result({ candidates: [candidate(), candidate(), candidate()] }),
      context,
    ),
  );
  const failed = candidate({
    checks: [
      {
        check_id: "compiler",
        category: "compiler",
        status: "modeled_failure",
        detail: "SYNTHETIC",
        blocker_codes: ["geometry_invalid"],
      },
    ],
  });
  assert.throws(() =>
    validateSearch(result({ candidates: [failed] }), context),
  );
  assert.throws(() =>
    validateSearch(
      result({ candidates: [candidate({ status: "rejected" })] }),
      context,
    ),
  );
  assert.throws(() =>
    validateSearch(result({ physical_verification: "passed" }), context),
  );
});

test("exhaustion and infeasibility stay distinct", () => {
  const exhausted = result({
    status: "search_exhausted",
    exhausted: "node_budget",
    candidates: [],
  });
  assert.equal(validateSearch(exhausted, context).exhausted, "node_budget");
  assert.throws(() =>
    validateSearch({ ...exhausted, exhausted: null }, context),
  );
  assert.equal(
    validateSearch(result({ status: "infeasible", candidates: [] }), context)
      .status,
    "infeasible",
  );
  assert.throws(() =>
    validateSearch(result({ status: "infeasible" }), context),
  );
});

test("probes must belong to the same search and carry a valid report", () => {
  const probe = {
    search_id: searchId,
    identity,
    parameter: "footprint_depth_mm",
    value_mm: 90,
    status: "evaluated",
    report: candidate(),
    changed_piece_ids: ["stand-base", "stand-brace"],
    blockers: [],
    physical_verification: "not_attempted",
  };
  assert.equal(validateProbe(probe, context, searchId).status, "evaluated");
  assert.throws(() => validateProbe(probe, context, "b".repeat(64)));
  assert.throws(() =>
    validateProbe({ ...probe, parameter: "lip_mm" }, context, searchId),
  );
  assert.throws(() =>
    validateProbe({ ...probe, report: { bad: true } }, context, searchId),
  );
});

test("selection results require a saved version when accepted", () => {
  assert.equal(
    validateSelection({ status: "blocked", blockers: [] }).status,
    "blocked",
  );
  assert.throws(() => validateSelection({ status: "accepted" }));
});

function respond(status, body) {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
}

test("ambiguous failures keep a selection retryable; definite ones release it", async () => {
  const original = globalThis.fetch;
  const api = synthesisApi("token", "project-a");
  const signal = new AbortController().signal;
  const body = selectionBody(context, searchId, design, "key-0000001");
  const select = () => api.select(body, signal);
  try {
    globalThis.fetch = async () => {
      throw new TypeError("network");
    };
    await assert.rejects(
      select(),
      (e) => e instanceof SynthesisRequestError && e.retry,
    );
    globalThis.fetch = respond(500, { message: "no code" });
    await assert.rejects(select(), (e) => e.retry && !e.stale);
    globalThis.fetch = respond(409, {
      code: "stale_version",
      message: "changed",
    });
    await assert.rejects(select(), (e) => !e.retry && e.stale);
    globalThis.fetch = respond(409, {
      code: "idempotency_conflict",
      message: "differs",
    });
    await assert.rejects(select(), (e) => !e.retry && !e.stale);
    const sent = [];
    globalThis.fetch = async (url, init) => {
      sent.push([url, JSON.parse(init.body)]);
      return new Response(JSON.stringify({ status: "blocked", blockers: [] }));
    };
    await select();
    assert.equal(sent[0][0], "/api/projects/project-a/synthesis/select");
    assert.equal(sent[0][1].idempotency_key, "key-0000001");
    assert.equal(sent[0][1].user_selected, true);
    assert.equal(sent[0][1].expected_last_event_id, null);
  } finally {
    globalThis.fetch = original;
  }
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

test("a selection receipt survives reload and is scoped to owner and project", async () => {
  const storage = new MemoryStorage();
  const body = selectionBody(context, searchId, design, "key-0000001");
  assert.equal(validSelectRequest(body), true);
  assert.equal(validSelectRequest({ ...body, extra: 1 }), false);
  await selectionReceipts.retain("token-a", "project-a", body, storage);
  assert.deepEqual(
    await selectionReceipts.pending("token-a", "project-a", storage),
    body,
  );
  assert.equal(
    await selectionReceipts.pending("token-b", "project-a", storage),
    null,
  );
  assert.equal(
    await selectionReceipts.pending("token-a", "project-b", storage),
    null,
  );
  const other = selectionBody(context, searchId, design, "key-0000002");
  await assert.rejects(
    selectionReceipts.retain("token-a", "project-a", other, storage),
  );
  // The MetaMuse receipt is independent of the selection receipt.
  assert.equal(
    await museReceipts.pending("token-a", "project-a", storage),
    null,
  );
  await selectionReceipts.clear("token-a", "project-a", other, storage);
  assert.notEqual(
    await selectionReceipts.pending("token-a", "project-a", storage),
    null,
  );
  await selectionReceipts.clear("token-a", "project-a", body, storage);
  assert.equal(
    await selectionReceipts.pending("token-a", "project-a", storage),
    null,
  );
  const [key] = [...storage.values.keys()];
  assert.equal(key, undefined);
  await selectionReceipts.retain("token-a", "project-a", body, storage);
  const [stored] = [...storage.values.keys()];
  storage.setItem(stored, "{not json");
  await assert.rejects(
    selectionReceipts.pending("token-a", "project-a", storage),
    /cannot be verified/,
  );
});

test("a malformed success keeps the key; blocked is not called an active build", async () => {
  const original = globalThis.fetch;
  const api = synthesisApi("token", "project-a");
  const signal = new AbortController().signal;
  const body = selectionBody(context, searchId, design, "key-0000001");
  try {
    globalThis.fetch = respond(200, { status: "accepted" });
    await assert.rejects(api.select(body, signal), (e) => e.retry === true);
    globalThis.fetch = respond(409, { code: "blocked", message: "x" });
    await assert.rejects(
      api.select(body, signal),
      (e) => !e.retry && !/active/i.test(e.message),
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("MetaMuse answers must match the request and keep engine checks valid", () => {
  const request = {
    expected_inventory_revision_id: "inventory-a",
    expected_active_version_id: null,
    expected_last_event_id: null,
    search_id: searchId,
    idempotency_key: "muse-0000001",
    question: null,
    provider_context_consented: true,
  };
  const answer = {
    project_id: "project-a",
    search_id: searchId,
    tool_name: "compare_stand_designs",
    prompt_version: "design-comparison-v1",
    explanation: {
      search_id: searchId,
      summary: "SYNTHETIC",
      candidate_notes: [],
      unresolved: [],
      questions: [],
    },
    engine_probe: null,
    usage: { input_tokens: 1, output_tokens: 1 },
    physical_status: "not_verified",
    replayed: false,
  };
  assert.equal(validateMuse(answer, "project-a", request).search_id, searchId);
  assert.throws(() =>
    validateMuse(
      { ...answer, search_id: "b".repeat(64) },
      "project-a",
      request,
    ),
  );
  assert.throws(() =>
    validateMuse(
      { ...answer, physical_status: "passed" },
      "project-a",
      request,
    ),
  );
  const failed = candidate({
    checks: [
      {
        check_id: "compiler",
        category: "compiler",
        status: "modeled_failure",
        detail: "SYNTHETIC",
        blocker_codes: [],
      },
    ],
  });
  assert.throws(() =>
    validateMuse(
      {
        ...answer,
        engine_probe: { status: "evaluated", report: failed },
      },
      "project-a",
      request,
    ),
  );
});
