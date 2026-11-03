import assert from "node:assert/strict";
import { test } from "node:test";
import {
  requestAnalysis,
  validateAnalysis,
  validateContext,
} from "../src/components/stability-report/client.ts";
const expected = {
  projectId: "p",
  planVersionId: "v",
  inventoryRevisionId: "i",
};
const context = {
  project_id: "p",
  plan_version_id: "v",
  inventory_revision_id: "i",
  last_event_id: null,
};
const response = () => ({
  ...context,
  status: "complete",
  blockers: [],
  report: {
    identity: {
      project_id: "p",
      plan_version_id: "v",
      inventory_revision: "i",
      history_cursor: null,
    },
    status: "modeled_pass",
    coverage: "complete",
    unresolved_predicates: [],
    overlays: [],
    policy: { required_case_ids: ["upright"], required_check_types: ["tip"] },
    results: [
      {
        case_id: "upright",
        check_type: "tip",
        status: "modeled_pass",
        computation: "complete",
        explanation: "Modeled",
        unresolved_predicates: [],
        quantities: [],
      },
    ],
  },
});
test("explicit empty history is valid while missing and stale context are rejected", () => {
  assert.equal(validateContext(context, expected).last_event_id, null);
  for (const changed of [
    { last_event_id: undefined },
    { project_id: "other" },
    { inventory_revision_id: "old" },
    { plan_version_id: "old" },
  ])
    assert.throws(
      () => validateContext({ ...context, ...changed }, expected),
      /Reload/,
    );
});
test("unknown geometry stays a blocker and cannot masquerade as complete", () => {
  const blocked = {
    ...context,
    status: "needs_geometry",
    blockers: ["Canonical geometry unavailable"],
    report: null,
  };
  assert.equal(validateAnalysis(blocked, expected, null).report, null);
  assert.throws(
    () => validateAnalysis({ ...blocked, status: "complete" }, expected, null),
    /requires a report/,
  );
});
test("stale response and false aggregate pass are rejected", () => {
  assert.throws(() => validateAnalysis(response(), expected, "later"), /stale/);
  for (const mutation of [
    (r) => {
      r.report.results = [];
    },
    (r) => {
      r.report.results[0].computation = "numerical_failure";
    },
    (r) => {
      r.report.results[0].status = "unsupported";
    },
    (r) => {
      r.report.unresolved_predicates = ["Unknown mass"];
    },
    (r) => {
      r.report.identity.history_cursor = "old";
    },
    (r) => {
      r.report.results[0].quantities = [{ kind: "unknown" }];
    },
  ]) {
    const r = response();
    mutation(r);
    assert.throws(() => validateAnalysis(r, expected, null));
  }
});
test("nonfinite overlay points cannot reach the diagram", () => {
  const r = response();
  r.report.overlays = [
    { case_id: "upright", center_of_mass: { x: Infinity, y: 0, z: 0 } },
  ];
  assert.throws(() => validateAnalysis(r, expected, null), /overlay/);
});
test("analysis sends the exact global cursor including null and never retries", async () => {
  const old = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = async (url, init) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify(calls.length === 1 ? context : response()),
        { status: 200 },
      );
    };
    await requestAnalysis("owner", expected, new AbortController().signal);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].init.headers.Authorization, "Bearer owner");
    assert.deepEqual(JSON.parse(calls[1].init.body), {
      plan_version_id: "v",
      expected_inventory_revision_id: "i",
      expected_last_event_id: null,
    });
    calls.length = 0;
    globalThis.fetch = async () => {
      calls.push(1);
      return new Response("", { status: 503 });
    };
    await assert.rejects(
      requestAnalysis("owner", expected, new AbortController().signal),
      /unavailable/,
    );
    assert.equal(calls.length, 1);
  } finally {
    globalThis.fetch = old;
  }
});
test("stale inventory aborts before the analysis POST", async () => {
  const old = globalThis.fetch;
  let count = 0;
  try {
    globalThis.fetch = async () => {
      count++;
      return new Response(
        JSON.stringify({ ...context, inventory_revision_id: "old" }),
      );
    };
    await assert.rejects(
      requestAnalysis("owner", expected, new AbortController().signal),
      /Reload/,
    );
    assert.equal(count, 1);
  } finally {
    globalThis.fetch = old;
  }
});
