// Design-search client checks on labeled SYNTHETIC responses; no physical pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SynthesisRequestError,
  domainValues,
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
  const select = () => api.select(context, searchId, design, "key-1", signal);
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
    assert.equal(sent[0][1].idempotency_key, "key-1");
    assert.equal(sent[0][1].user_selected, true);
    assert.equal(sent[0][1].expected_last_event_id, null);
  } finally {
    globalThis.fetch = original;
  }
});
