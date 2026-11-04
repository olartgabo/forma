import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

// Resolve the same extensionless TypeScript dependency that Next bundles.
registerHooks({
  resolve(specifier, context, next) {
    try {
      return next(specifier, context);
    } catch (error) {
      if (
        error.code === "ERR_MODULE_NOT_FOUND" &&
        specifier.startsWith(".") &&
        !specifier.endsWith(".ts")
      )
        return next(`${specifier}.ts`, context);
      throw error;
    }
  },
});
const { validateView, requestView } =
  await import("../src/components/assembly-view/client.ts");
const expected = {
  projectId: "p",
  planVersionId: "v",
  inventoryRevisionId: "i",
};
const identity = {
  project_id: "p",
  plan_version_id: "v",
  inventory_revision_id: "i",
  last_event_id: null,
};
function response() {
  const vertices = [
    { x: 0, y: 0, z: 0 },
    { x: 0.1, y: 0, z: 0 },
    { x: 0.1, y: 0.1, z: 0 },
    { x: 0, y: 0.1, z: 0 },
  ];
  return {
    ...identity,
    evidence_revision: "a".repeat(64),
    status: "ready",
    overlay_coverage: "unavailable",
    blockers: [],
    operation_parts: [{ operation_id: "cut", part_ids: ["base"] }],
    geometry: {
      project_id: "p",
      plan_version_id: "v",
      history_cursor: null,
      producer_version: "canonical",
      geometry_hash: "b".repeat(64),
      coordinate_frame: "x_across_y_rearward_z_up_m",
      stage: "planned_preview",
      state_basis: "nominal",
      active_part_ids: ["base"],
      nominal_joint_ids: [],
      attached_joint_ids: [],
      completed_operation_ids: [],
      assumption_ids: ["nominal"],
      assumptions: ["Nominal only"],
      ground_polygon: vertices,
      facets: [
        {
          facet_id: "base-face",
          part_id: "base",
          centroid: { x: 0.05, y: 0.05, z: 0 },
          vertices,
          area_fraction: 1,
        },
      ],
    },
  };
}
test("accept canonical geometry and honest unsupported fallback", () => {
  assert.equal(validateView(response(), expected, null).status, "ready");
  const unavailable = {
    ...response(),
    status: "unsupported",
    geometry: null,
    operation_parts: [],
    blockers: ["Intermediate unsupported"],
  };
  assert.equal(validateView(unavailable, expected, null).geometry, null);
});
test("reject foreign history, geometry, invalid facets and manual links", () => {
  for (const mutate of [
    (r) => (r.project_id = "other"),
    (r) => (r.last_event_id = "old"),
    (r) => (r.geometry.plan_version_id = "other"),
    (r) => (r.geometry.facets[0].vertices[0].x = Infinity),
    (r) => r.geometry.facets.push(...Array(33).fill(r.geometry.facets[0])),
    (r) => (r.operation_parts[0].part_ids = ["foreign"]),
    (r) => r.operation_parts.push(r.operation_parts[0]),
    (r) => (r.geometry.stage = "partial"),
    (r) => (r.status = "unsupported"),
  ]) {
    const value = response();
    mutate(value);
    assert.throws(() => validateView(value, expected, null));
  }
});
test("fetch only scoped context and view GETs with explicit null cursor", async () => {
  const original = globalThis.fetch,
    calls = [];
  try {
    globalThis.fetch = async (url, init) => {
      calls.push({ url, init });
      return Response.json(calls.length === 1 ? identity : response());
    };
    const controller = new AbortController();
    assert.equal(
      (await requestView("synthetic", expected, controller.signal)).status,
      "ready",
    );
    assert.equal(calls.length, 2);
    assert.ok(calls[0].url.includes("/stability/context?"));
    assert.ok(calls[1].url.includes("/assembly-view?"));
    assert.ok(calls[1].url.endsWith("expected_last_event_id="));
    assert.ok(
      calls.every(
        (call) =>
          !call.init.method &&
          call.init.cache === "no-store" &&
          call.init.signal === controller.signal,
      ),
    );
  } finally {
    globalThis.fetch = original;
  }
});
test("a foreign context stops before loading a scene", async () => {
  const original = globalThis.fetch;
  let count = 0;
  try {
    globalThis.fetch = async () => {
      count++;
      return Response.json({ ...identity, project_id: "other" });
    };
    await assert.rejects(
      requestView("synthetic", expected, new AbortController().signal),
    );
    assert.equal(count, 1);
  } finally {
    globalThis.fetch = original;
  }
});
