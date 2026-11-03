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

import {
  confirmations,
  measurementContext,
  measurementsFromForm,
  MeasurementSaveError,
  saveMeasurements,
} from "../src/components/stability-report/measurement-client.ts";

function measuredForm() {
  const form = new FormData();
  for (const prefix of ["stand", "portrait", "landscape"]) {
    for (const [field, value] of Object.entries({
      mass_g: "100",
      mass_resolution_g: "1",
      x_mm: "-10",
      y_mm: "30",
      z_mm: "50",
      position_resolution_mm: "0.5",
      method: "Synthetic balance test data, not a physical observation",
    }))
      form.set(`${prefix}_${field}`, value);
    if (prefix !== "stand")
      form.set(`${prefix}_pose`, "Synthetic upright device pose");
  }
  for (const [key, value] of Object.entries({
    contact_x_min_mm: "-30",
    contact_x_max_mm: "30",
    contact_y_min_mm: "0",
    contact_y_max_mm: "80",
    contact_resolution_mm: "1",
    contact_method: "Synthetic ruler example",
    required_margin_mm: "2",
  }))
    form.set(key, value);
  for (const [key] of confirmations) form.set(key, "on");
  form.set("user_confirmed", "on");
  return form;
}
test("measurement entry converts grams/mm exactly and retains both device cases", () => {
  const result = measurementsFromForm(measuredForm());
  assert.equal(result.stand.mass_kg, 0.1);
  assert.equal(result.stand.mass_resolution_kg, 0.001);
  assert.deepEqual(result.stand.center_of_mass_m, {
    x: -0.01,
    y: 0.03,
    z: 0.05,
  });
  assert.equal(result.stand.position_resolution_m, 0.0005);
  assert.equal(result.support.x_min_m, -0.03);
  assert.equal(result.required_margin_m, 0.002);
  assert.deepEqual(
    result.cases.map((c) => c.orientation),
    ["portrait", "landscape"],
  );
});
test("measurement entry never converts blanks, invalid values or absent confirmations to measurements", () => {
  for (const [key, value] of [
    ["stand_x_mm", ""],
    ["stand_mass_g", "Infinity"],
    ["stand_mass_g", "NaN"],
    ["stand_mass_g", "0x10"],
    ["stand_mass_g", "0"],
    ["portrait_method", ""],
    ["landscape_pose", ""],
    ["contact_resolution_mm", "0"],
    ["contact_x_max_mm", "-40"],
    ["required_margin_mm", "-1"],
    ["user_confirmed", ""],
    ...confirmations.map(([key]) => [key, ""]),
  ]) {
    const form = measuredForm();
    form.set(key, value);
    assert.throws(() => measurementsFromForm(form), key);
  }
});
test("measurement context is loaded before editing and rejects a foreign revision", async () => {
  const old = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.cache, "no-store");
      return new Response(JSON.stringify(context));
    };
    assert.equal(
      (
        await measurementContext(
          "owner",
          expected,
          new AbortController().signal,
        )
      ).last_event_id,
      null,
    );
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ ...context, inventory_revision_id: "foreign" }),
      );
    await assert.rejects(
      measurementContext("owner", expected, new AbortController().signal),
      /context changed/,
    );
  } finally {
    globalThis.fetch = old;
  }
});
test("measurement save preserves captured cursor and exact retry payload without refreshing context", async () => {
  const old = globalThis.fetch;
  const payload = {
    plan_version_id: "v",
    expected_inventory_revision_id: "i",
    expected_last_event_id: "captured",
    idempotency_key: "same-key",
    user_confirmed: true,
    measurements: measurementsFromForm(measuredForm()),
  };
  const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, body: options.body });
      if (calls.length === 1) throw new Error("Synthetic network interruption");
      return new Response(
        JSON.stringify({
          ...context,
          last_event_id: "saved",
          measurement_id: "m",
          evidence_id: "e",
          replayed: true,
        }),
      );
    };
    await assert.rejects(
      saveMeasurements(
        "owner",
        expected,
        payload,
        new AbortController().signal,
      ),
      (e) => e instanceof MeasurementSaveError && e.uncertain,
    );
    const saved = await saveMeasurements(
      "owner",
      expected,
      payload,
      new AbortController().signal,
    );
    assert.equal(saved.replayed, true);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].body, calls[1].body);
    assert(calls.every((c) => c.url.endsWith("/measurements")));
    assert.equal(JSON.parse(calls[1].body).expected_last_event_id, "captured");
  } finally {
    globalThis.fetch = old;
  }
});
test("measurement save distinguishes definitive rejection from unknown outcome and foreign response", async () => {
  const old = globalThis.fetch;
  const payload = {
    plan_version_id: "v",
    expected_inventory_revision_id: "i",
    expected_last_event_id: null,
    idempotency_key: "key",
    user_confirmed: true,
    measurements: measurementsFromForm(measuredForm()),
  };
  try {
    for (const [status, uncertain] of [
      [409, false],
      [422, false],
      [401, true],
      [403, true],
      [404, true],
      [503, true],
    ]) {
      globalThis.fetch = async () =>
        new Response(
          JSON.stringify({
            code: status === 409 ? "stale_version" : "validation_error",
          }),
          { status },
        );
      await assert.rejects(
        saveMeasurements(
          "owner",
          expected,
          payload,
          new AbortController().signal,
        ),
        (e) => e instanceof MeasurementSaveError && e.uncertain === uncertain,
      );
    }
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          ...context,
          project_id: "foreign",
          last_event_id: "saved",
          measurement_id: "m",
          evidence_id: "e",
          replayed: false,
        }),
      );
    await assert.rejects(
      saveMeasurements(
        "owner",
        expected,
        payload,
        new AbortController().signal,
      ),
      (e) => e instanceof MeasurementSaveError && e.uncertain,
    );
  } finally {
    globalThis.fetch = old;
  }
});

import {
  pendingMeasurements,
  retainMeasurement,
  clearMeasurement,
  validPendingPayload,
} from "../src/components/stability-report/measurement-pending.ts";
function recoveryStorage() {
  const values = new Map();
  return {
    get length() {
      return values.size;
    },
    key(index) {
      return [...values.keys()][index] ?? null;
    },
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
    clear() {
      values.clear();
    },
  };
}
function recoveryPayload() {
  return {
    plan_version_id: "plan-original",
    expected_inventory_revision_id: "inventory-original",
    expected_last_event_id: "event-original",
    idempotency_key: "original-save-key",
    user_confirmed: true,
    measurements: measurementsFromForm(measuredForm()),
  };
}
test("durable recovery retains exact body across remounts, plan/inventory changes and excludes other owners", async () => {
  const storage = recoveryStorage();
  const payload = recoveryPayload();
  const retained = await retainMeasurement(
    "owner-secret",
    "project-original",
    payload,
    storage,
  );
  assert(!retained.key.includes("owner-secret"));
  assert(!storage.getItem(retained.key).includes("owner-secret"));
  const recovered = await pendingMeasurements(
    "owner-secret",
    "project-original",
    storage,
  );
  assert.deepEqual(recovered[0].payload, payload);
  assert.deepEqual(
    await pendingMeasurements("different-owner", "project-original", storage),
    [],
  );
  assert.deepEqual(
    await pendingMeasurements("owner-secret", "another-project", storage),
    [],
  );
  await assert.rejects(
    retainMeasurement(
      "owner-secret",
      "project-original",
      {
        ...payload,
        plan_version_id: "plan-new",
        expected_inventory_revision_id: "inventory-new",
        idempotency_key: "new-save-key",
      },
      storage,
    ),
    /unresolved/,
  );
  assert.deepEqual(
    (await pendingMeasurements("owner-secret", "project-original", storage))[0]
      .payload,
    payload,
  );
  assert.deepEqual(
    await retainMeasurement(
      "owner-secret",
      "project-original",
      payload,
      storage,
    ),
    retained,
  );
  await clearMeasurement("owner-secret", retained, storage);
  assert.equal(
    (await pendingMeasurements("owner-secret", "project-original", storage))
      .length,
    0,
  );
});
test("browser persistence failure prevents retention and malformed stored bodies cannot be replayed", async () => {
  const storage = recoveryStorage();
  const payload = recoveryPayload();
  const unwritable = {
    ...storage,
    setItem() {
      throw new Error("Storage unavailable");
    },
  };
  await assert.rejects(
    retainMeasurement("owner", "project-original", payload, unwritable),
    /Storage unavailable/,
  );
  const record = await retainMeasurement(
    "owner",
    "project-original",
    payload,
    storage,
  );
  storage.setItem(
    record.key,
    JSON.stringify({
      version: 1,
      project_id: "project-original",
      payload: { ...payload, endpoint: "https://outside.invalid" },
    }),
  );
  await assert.rejects(
    pendingMeasurements("owner", "project-original", storage),
    /invalid identity or values/,
  );
  storage.setItem(record.key, " ".repeat(32769));
  await assert.rejects(
    pendingMeasurements("owner", "project-original", storage),
    /cannot be verified/,
  );
});
test("recovery schema rejects fabricated cases, confirmation, fields, nonfinite values and identity", () => {
  for (const change of [
    (p) => {
      p.user_confirmed = false;
    },
    (p) => {
      p.measurements.cases.pop();
    },
    (p) => {
      p.measurements.cases[1].orientation = "portrait";
    },
    (p) => {
      p.measurements.stand.mass_kg = Infinity;
    },
    (p) => {
      p.measurements.actual_contacts_confirmed = false;
    },
    (p) => {
      p.plan_version_id = "../other";
    },
    (p) => {
      p.measurements.stand.method = "x".repeat(2001);
    },
    (p) => {
      p.measurements.support.x_max_m = p.measurements.support.x_min_m;
    },
    (p) => {
      p.measurements.cases[0].device.extra = "arbitrary";
    },
  ]) {
    const payload = recoveryPayload();
    change(payload);
    assert.equal(validPendingPayload(payload), false);
  }
  assert.equal(validPendingPayload(recoveryPayload()), true);
});
