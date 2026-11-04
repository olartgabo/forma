// Saved-report validators on labeled synthetic responses; no provider or physical pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clearMuse,
  pendingMuse,
  retainMuse,
} from "../src/components/stability-report/muse-pending.ts";
import {
  StabilityRequestError,
  stabilityApi,
  validateComparison,
  validateHistory,
  validateMuse,
  validateSave,
  validateSummary,
} from "../src/components/stability-report/history-client.ts";

const expected = {
  projectId: "project-a",
  planVersionId: "plan-a",
  inventoryRevisionId: "inventory-a",
};
const hash = (c) => c.repeat(64);
const id = (c) => `stability-report-${hash(c)}`;
function summary(c, overrides = {}) {
  return {
    report_id: id(c),
    plan_version_id: "plan-a",
    inventory_revision_id: "inventory-a",
    history_cursor: "event-1",
    created_at: "2026-11-03T12:00:00Z",
    source: "builder",
    analysis_status: "complete",
    report_status: "modeled_pass",
    coverage: "complete",
    policy_id: "measured-point-policy",
    policy_version: "v1",
    case_ids: ["portrait", "landscape"],
    freshness: { current: true, stale_reasons: [] },
    ...overrides,
  };
}
function report(c) {
  return {
    identity: {
      project_id: "project-a",
      plan_version_id: "plan-a",
      inventory_revision: "inventory-a",
      history_cursor: "event-1",
    },
    cache_hash: hash(c),
    status: "modeled_pass",
    coverage: "complete",
    unresolved_predicates: [],
    results: [
      {
        case_id: "portrait",
        check_type: "tip",
        status: "modeled_pass",
        computation: "complete",
        explanation: "Synthetic",
        unresolved_predicates: [],
        quantities: [],
      },
    ],
    policy: { required_case_ids: ["portrait"], required_check_types: ["tip"] },
  };
}
const analysis = (c) => ({
  project_id: "project-a",
  plan_version_id: "plan-a",
  inventory_revision_id: "inventory-a",
  last_event_id: "event-1",
  status: "complete",
  report: report(c),
  blockers: [],
});

test("a stale summary must name reasons and another plan is never current", () => {
  assert.equal(validateSummary(summary("a"), expected).report_id, id("a"));
  const stale = summary("a", {
    freshness: { current: false, stale_reasons: ["history_changed"] },
  });
  assert.equal(validateSummary(stale, expected).freshness.current, false);
  for (const bad of [
    summary("a", { freshness: { current: false, stale_reasons: [] } }),
    summary("a", {
      freshness: { current: true, stale_reasons: ["plan_changed"] },
    }),
    summary("a", { plan_version_id: "plan-old" }),
    summary("a", { freshness: { current: false, stale_reasons: ["vibes"] } }),
    summary("a", { report_id: "report-anything" }),
  ])
    assert.throws(() => validateSummary(bad, expected), /invalid/);
  const historical = summary("a", {
    plan_version_id: "plan-old",
    freshness: { current: false, stale_reasons: ["plan_changed"] },
  });
  assert.equal(
    validateSummary(historical, expected).plan_version_id,
    "plan-old",
  );
});

test("a saved report ID must be the content hash of the returned report", () => {
  const saved = {
    analysis: analysis("a"),
    saved: summary("a"),
    cached: false,
    replayed: false,
  };
  assert.equal(
    validateSave(saved, expected, "event-1").saved.report_id,
    id("a"),
  );
  assert.throws(
    () => validateSave({ ...saved, saved: summary("b") }, expected, "event-1"),
    /invalid/,
  );
  assert.throws(() => validateSave(saved, expected, "event-2"), /stale/);
  const blocked = {
    analysis: { ...analysis("a"), status: "needs_measurement", report: null },
    saved: null,
    cached: false,
  };
  assert.equal(validateSave(blocked, expected, "event-1").saved, null);
  assert.throws(
    () => validateSave({ ...saved, saved: null }, expected, "event-1"),
    /invalid/,
  );
});

test("history rejects duplicates and foreign projects", () => {
  const history = {
    project_id: "project-a",
    reports: [summary("a"), summary("b")],
  };
  assert.equal(validateHistory(history, expected).reports.length, 2);
  assert.throws(
    () =>
      validateHistory(
        { ...history, reports: [summary("a"), summary("a")] },
        expected,
      ),
    /invalid/,
  );
  assert.throws(
    () => validateHistory({ ...history, project_id: "project-b" }, expected),
    /invalid/,
  );
});

test("a comparison cannot rank unresolved or mismatched reports", () => {
  const base = {
    project_id: "project-a",
    first: summary("a"),
    second: summary("b"),
    comparable: true,
    mismatches: [],
    rows: [
      {
        case_id: "portrait",
        check_type: "tip",
        first_status: "modeled_pass",
        second_status: "modeled_fail",
        first_margin_m: 0.01,
        second_margin_m: -0.01,
        outcome: "first_larger_margin",
      },
    ],
  };
  assert.equal(
    validateComparison(base, expected, id("a"), id("b")).comparable,
    true,
  );
  const unresolved = structuredClone(base);
  unresolved.rows[0].second_status = "needs_measurement";
  assert.throws(
    () => validateComparison(unresolved, expected, id("a"), id("b")),
    /invalid/,
  );
  unresolved.rows[0].outcome = "unknown";
  assert.equal(
    validateComparison(unresolved, expected, id("a"), id("b")).rows[0].outcome,
    "unknown",
  );
  const mismatch = { ...base, comparable: false, mismatches: ["policy"] };
  assert.throws(
    () => validateComparison(mismatch, expected, id("a"), id("b")),
    /invalid/,
  );
  assert.throws(
    () =>
      validateComparison(
        { ...base, mismatches: ["x"] },
        expected,
        id("a"),
        id("b"),
      ),
    /invalid/,
  );
  assert.throws(
    () => validateComparison(base, expected, id("b"), id("a")),
    /invalid/,
  );
});

test("a MetaMuse answer must cite its tool report and stay unverified", () => {
  const result = {
    project_id: "project-a",
    plan_version_id: "plan-a",
    mode: "analyze_current",
    tool_name: "analyze_stability",
    report: summary("a", { source: "muse_tool" }),
    explanation: { report_id: id("a"), summary: "Synthetic explanation" },
    usage: { model_calls: 2 },
    physical_status: "not_verified",
  };
  assert.equal(validateMuse(result, expected).report.report_id, id("a"));
  assert.throws(
    () =>
      validateMuse(
        {
          ...result,
          explanation: { ...result.explanation, report_id: id("b") },
        },
        expected,
      ),
    /invalid/,
  );
  assert.throws(
    () => validateMuse({ ...result, physical_status: "passed" }, expected),
    /invalid/,
  );
});

test("requests bind the current context, consent and an idempotency key", async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    if (url.includes("/context"))
      return Response.json({
        project_id: "project-a",
        plan_version_id: "plan-a",
        inventory_revision_id: "inventory-a",
        last_event_id: "event-1",
      });
    if (url.endsWith("/muse-explanations"))
      return Response.json(
        { code: "consent_required", message: "x" },
        { status: 422 },
      );
    return Response.json({
      analysis: analysis("a"),
      saved: summary("a"),
      cached: false,
    });
  };
  try {
    const api = stabilityApi("owner", "project-a");
    const signal = new AbortController().signal;
    await api.save(expected, "stability-key-1", signal);
    const body = JSON.parse(calls[1].init.body);
    assert.deepEqual(body, {
      plan_version_id: "plan-a",
      expected_inventory_revision_id: "inventory-a",
      expected_last_event_id: "event-1",
      idempotency_key: "stability-key-1",
    });
    assert.equal(calls[1].init.headers.Authorization, "Bearer owner");
    const prepared = await api.prepareMuse(
      expected,
      {
        key: "stability-key-2",
        reportId: id("a"),
        question: " ",
        consented: false,
      },
      signal,
    );
    const error = await api.sendMuse(expected, prepared, signal).then(
      () => null,
      (e) => e,
    );
    assert.ok(error instanceof StabilityRequestError);
    assert.match(error.message, /Confirm sharing/);
    assert.equal(error.ambiguous, false, "a refusal is a definite answer");
    const muse = JSON.parse(calls[3].init.body);
    assert.deepEqual(muse, prepared, "the prepared body is sent unchanged");
    assert.equal(muse.mode, "explain_report");
    assert.equal(muse.report_id, id("a"));
    assert.equal(muse.question, null);
    assert.equal(muse.provider_context_consented, false);
    assert.equal("measurements" in muse, false);
  } finally {
    globalThis.fetch = original;
  }
});

test("an aborted request does not resolve", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (_, init) =>
    new Promise((_, reject) =>
      init.signal.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")),
      ),
    );
  try {
    const controller = new AbortController();
    const pending = stabilityApi("owner", "project-a").history(
      expected,
      controller.signal,
    );
    controller.abort();
    await assert.rejects(pending, /stopped or timed out/);
  } finally {
    globalThis.fetch = original;
  }
});

test("a replayed save may be stale but must say so", () => {
  const stale = summary("a", {
    freshness: { current: false, stale_reasons: ["history_changed"] },
  });
  const replay = {
    analysis: analysis("a"),
    saved: stale,
    cached: false,
    replayed: true,
  };
  // The original calculation was at event-1; the project is now at event-2.
  assert.equal(
    validateSave(replay, expected, "event-2").saved.freshness.current,
    false,
  );
  assert.throws(
    () => validateSave({ ...replay, saved: summary("a") }, expected, "event-2"),
    /invalid/,
    "an old calculation cannot be labeled current",
  );
  assert.throws(
    () => validateSave({ ...replay, replayed: false }, expected, "event-2"),
    /stale/,
  );
});

class MemoryStorage {
  map = new Map();
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
}
const museBody = (key = "stability-muse-0001") => ({
  plan_version_id: "plan-a",
  expected_inventory_revision_id: "inventory-a",
  expected_last_event_id: "event-1",
  idempotency_key: key,
  mode: "analyze_current",
  report_id: null,
  question: null,
  provider_context_consented: true,
});

test("a sent MetaMuse request is retained exactly until answered", async () => {
  const storage = new MemoryStorage();
  assert.equal(await pendingMuse("owner", "project-a", storage), null);
  await retainMuse("owner", "project-a", museBody(), storage);
  assert.deepEqual(
    await pendingMuse("owner", "project-a", storage),
    museBody(),
  );
  // Another owner or project never sees the receipt.
  assert.equal(await pendingMuse("other", "project-a", storage), null);
  assert.equal(await pendingMuse("owner", "project-b", storage), null);
  await assert.rejects(
    retainMuse("owner", "project-a", museBody("stability-muse-0002"), storage),
    /unresolved/,
  );
  await assert.rejects(
    retainMuse(
      "owner",
      "project-a",
      { ...museBody(), provider_context_consented: false },
      new MemoryStorage(),
    ),
    /cannot be safely retained/,
  );
  await clearMuse("owner", "project-a", museBody(), storage);
  assert.equal(await pendingMuse("owner", "project-a", storage), null);
  const [key] =
    (await retainMuse("owner", "project-a", museBody(), storage),
    [...storage.map.keys()]);
  storage.setItem(key, storage.getItem(key).replace("event-1", "event-9!"));
  await assert.rejects(pendingMuse("owner", "project-a", storage), /verified/);
});

test("a completed POST with a lost response is retried with the same body", async () => {
  const calls = [];
  const original = globalThis.fetch;
  const answer = {
    project_id: "project-a",
    plan_version_id: "plan-a",
    mode: "analyze_current",
    tool_name: "analyze_stability",
    report: summary("a", {
      source: "muse_tool",
      freshness: { current: false, stale_reasons: ["history_changed"] },
    }),
    explanation: { report_id: id("a"), summary: "Synthetic explanation" },
    usage: { model_calls: 2 },
    physical_status: "not_verified",
    replayed: true,
  };
  let attempt = 0;
  globalThis.fetch = async (url, init = {}) => {
    calls.push(JSON.parse(init.body));
    attempt += 1;
    // The server completed the first POST, but its response never arrived.
    if (attempt === 1) throw new TypeError("Failed to fetch");
    if (attempt === 2)
      return new Response('{"project_id":', {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    return Response.json(answer);
  };
  try {
    const api = stabilityApi("owner", "project-a");
    const signal = new AbortController().signal;
    const body = museBody();
    for (const _ of [1, 2]) {
      const error = await api.sendMuse(expected, body, signal).then(
        () => null,
        (e) => e,
      );
      assert.ok(error instanceof StabilityRequestError);
      assert.equal(error.ambiguous, true);
    }
    const result = await api.sendMuse(expected, body, signal);
    assert.equal(result.replayed, true);
    assert.equal(result.report.freshness.current, false);
    assert.deepEqual(calls, [body, body, body]);
  } finally {
    globalThis.fetch = original;
  }
});

test("unknown-outcome and in-progress answers keep the request retained", async () => {
  const original = globalThis.fetch;
  try {
    for (const [code, status, ambiguous] of [
      ["generation_outcome_unknown", 409, true],
      ["generation_in_progress", 409, true],
      ["stale_version", 409, false],
      ["invalid_response", 502, false],
    ]) {
      globalThis.fetch = async () =>
        Response.json({ code, message: "x" }, { status });
      const error = await stabilityApi("owner", "project-a")
        .sendMuse(expected, museBody(), new AbortController().signal)
        .then(
          () => null,
          (e) => e,
        );
      assert.equal(error.ambiguous, ambiguous, code);
    }
  } finally {
    globalThis.fetch = original;
  }
});
