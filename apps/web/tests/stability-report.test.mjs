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
const geometryResponse = () => {
  const vertices = [
    { x: 0, y: 0, z: 0 },
    { x: 0.1, y: 0, z: 0 },
    { x: 0.1, y: 0.1, z: 0 },
    { x: 0, y: 0.1, z: 0 },
  ];
  return {
    ...context,
    status: "needs_measurement",
    blockers: ["Body mass is unknown"],
    report: null,
    geometry_preview: {
      project_id: "p",
      plan_version_id: "v",
      history_cursor: null,
      producer_version: "nominal-v1",
      geometry_hash: "a".repeat(64),
      coordinate_frame: "x_across_y_rearward_z_up_m",
      stage: "planned_preview",
      state_basis: "nominal",
      active_part_ids: ["base"],
      nominal_joint_ids: [],
      attached_joint_ids: [],
      completed_operation_ids: [],
      facets: [
        {
          facet_id: "base-face",
          part_id: "base",
          vertices,
          centroid: { x: 0.05, y: 0.05, z: 0 },
          area_fraction: 1,
        },
      ],
      ground_polygon: vertices,
      assumption_ids: ["nominal_only"],
      assumptions: ["Nominal geometry only"],
    },
  };
};
test("nominal geometry is scoped and cannot claim physical completion or a calculation", () => {
  const value = geometryResponse();
  assert.equal(
    validateAnalysis(value, expected, null).geometry_preview.stage,
    "planned_preview",
  );
  assert.equal(validateAnalysis(value, expected, null).report, null);
  for (const mutation of [
    (g) => {
      g.project_id = "foreign";
    },
    (g) => {
      g.plan_version_id = "old";
    },
    (g) => {
      g.history_cursor = "old";
    },
    (g) => {
      g.geometry_hash = "not-a-hash";
    },
    (g) => {
      g.coordinate_frame = "pixels";
    },
    (g) => {
      g.state_basis = "observed";
    },
    (g) => {
      g.stage = "reported_assembled";
    },
    (g) => {
      g.attached_joint_ids = ["unreported"];
    },
    (g) => {
      g.facets[0].vertices[0].z = Infinity;
    },
    (g) => {
      g.facets[0].area_fraction = 0.5;
    },
    (g) => {
      g.facets[0].part_id = "foreign-part";
    },
    (g) => {
      g.facets = [];
    },
    (g) => {
      g.facets.push(structuredClone(g.facets[0]));
    },
  ]) {
    const changed = geometryResponse();
    mutation(changed.geometry_preview);
    assert.throws(
      () => validateAnalysis(changed, expected, null),
      /geometry preview/,
    );
  }
});
test("finite out-of-bounds centroids cannot overflow nominal SVG label projection", () => {
  for (const axis of ["x", "y", "z"]) {
    for (const value of [-1e304, -0.01, 0.11, 1e304]) {
      const response = geometryResponse();
      const facet = response.geometry_preview.facets[0];
      facet.centroid[axis] = value;
      assert.throws(
        () => validateAnalysis(response, expected, null),
        /geometry preview/,
      );
    }
  }
  const response = geometryResponse();
  response.geometry_preview.facets[0].vertices = Array.from(
    { length: 4 },
    () => ({ x: 0, y: 0, z: 0 }),
  );
  response.geometry_preview.facets[0].centroid = { x: 0, y: 1e304, z: 0 };
  assert.throws(
    () => validateAnalysis(response, expected, null),
    /geometry preview/,
  );
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
