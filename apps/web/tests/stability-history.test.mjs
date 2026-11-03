// Saved-report validators on labeled synthetic responses; no provider or physical pass.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
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
    await assert.rejects(
      api.askMuse(
        expected,
        {
          key: "stability-key-2",
          reportId: id("a"),
          question: " ",
          consented: false,
        },
        signal,
      ),
      /Confirm sharing/,
    );
    const muse = JSON.parse(calls[3].init.body);
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
    await assert.rejects(pending, /aborted/);
  } finally {
    globalThis.fetch = original;
  }
});
