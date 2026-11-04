import assert from "node:assert/strict";
import { test } from "node:test";
import {
  materialMeasurementChecklist,
  constructionPiecePresence,
  constructionStepTitle,
} from "../src/lib/muse-construction-guidance.ts";

test("saved checklist distinguishes unknown and unconfirmed dimensions and uses connector length only", () => {
  const measurement = {
    value: null,
    unit: "mm",
    source: "unknown",
    confirmed: false,
  };
  const stock = {
    kind: "sheet",
    width_mm: measurement,
    height_mm: { ...measurement, value: 250, source: "user_ruler" },
    thickness_mm: {
      ...measurement,
      value: 2,
      source: "user_ruler",
      confirmed: true,
    },
    remaining_length_mm: measurement,
  };
  assert.deepEqual(
    materialMeasurementChecklist(stock).map((m) => m.status),
    ["missing", "unconfirmed", "confirmed"],
  );
  for (const kind of ["tape", "cord"]) {
    const rows = materialMeasurementChecklist({
      ...stock,
      kind,
      remaining_length_mm: { ...measurement, value: 0, confirmed: true },
    });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].field, "remaining_length_mm");
    assert.equal(rows[0].value, 0);
  }
  assert.equal(
    stock.width_mm.value,
    null,
    "display never fills unknown dimensions",
  );
});

test("step names and piece presence follow engine identities without implying completed work", () => {
  const first = {
    action: "place",
    part_ids: ["base"],
    analysis: { facets: [{ part_id: "base" }] },
  };
  const next = {
    action: "join",
    part_ids: ["wall"],
    analysis: { facets: [{ part_id: "base" }, { part_id: "wall" }] },
  };
  const plan = {
    piece_catalog: [
      { part_id: "base", display_name: "Base panel" },
      { part_id: "wall", display_name: "Side wall" },
    ],
    steps: [first, next],
  };
  assert.equal(constructionStepTitle(plan, first), "Place Base panel");
  assert.equal(
    constructionPiecePresence(plan, first, "wall"),
    "Used in a later step",
  );
  assert.equal(
    constructionPiecePresence(plan, next, "wall"),
    "Focus of this step",
  );
  assert.equal(
    constructionPiecePresence(plan, next, "base"),
    "Present in this step",
  );
  assert.equal(
    constructionPiecePresence(plan, next, "absent"),
    "Not shown in this step",
  );
});
import {
  proposeConstruction,
  savedConstruction,
  authorizeConstructionReplacement,
  blockingConstructionReceipts,
  constructionReceipts,
  uncertainConstructionOutcome,
} from "../src/lib/muse-construction-client.ts";
import { validConstructionResult } from "../src/lib/construction-result.ts";
import {
  projectConstructionFacets,
  fitConstructionProjection,
  orthographicConstruction,
  constructionCamera,
} from "../src/lib/construction-projection.ts";

const body = {
  expected_revision_id: "inventory-one",
  user_notes: "A phone shelf",
  media_id: "photo-one",
  provider_context_consented: true,
  provider_transfer_consented: true,
  idempotency_key: "original-request",
};
const result = {
  project_id: "project-one",
  inventory_revision_id: "inventory-one",
  status: "needs_measurement",
  candidates: [],
  questions: ["Measure thickness"],
  diagnostics: {
    status: "ok",
    model: "test",
    elapsed_ms: 1,
    model_rounds: 1,
    tool_executions: 0,
    usage: null,
  },
};

test("construction client sends scoped consent and original request identity without credentials or redirects", async (t) => {
  let called = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    called++;
    assert.equal(url, "/api/projects/project-one/construction/propose");
    assert.deepEqual(JSON.parse(init.body), body);
    assert.equal(init.headers.Authorization, "Bearer owner-token");
    assert.equal(init.cache, "no-store");
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    return new Response(JSON.stringify(result), { status: 200 });
  });
  assert.deepEqual(
    await proposeConstruction("owner-token", "project-one", body),
    result,
  );
  assert.equal(called, 1);
});

test("construction client rejects a foreign revision result and never retries automatically", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return new Response(
      JSON.stringify({ ...result, inventory_revision_id: "other" }),
    );
  });
  await assert.rejects(proposeConstruction("secret", "project-one", body), {
    code: "invalid_response",
  });
  assert.equal(calls, 1);
});

test("construction client redacts raw provider messages and keeps uncertain outcomes explicit", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          code: "generation_outcome_unknown",
          message: "secret-provider-body",
        }),
        { status: 409 },
      ),
  );
  await assert.rejects(
    proposeConstruction("secret", "project-one", body),
    (e) =>
      e.code === "generation_outcome_unknown" && !e.message.includes("secret"),
  );
  for (const code of [
    "timeout",
    "network_error",
    "invalid_response",
    "generation_in_progress",
    "generation_outcome_unknown",
    "cancelled",
  ])
    assert.equal(uncertainConstructionOutcome(code), true);
  assert.equal(uncertainConstructionOutcome("rate_limit"), false);
});

test("construction client treats connection failure as unknown and performs one request", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    throw new Error("private network detail");
  });
  await assert.rejects(proposeConstruction("secret", "project-one", body), {
    code: "network_error",
  });
  assert.equal(calls, 1);
});

import {
  pendingConstruction,
  retainConstruction,
  clearConstruction,
  retainReplacementConstruction,
  validPendingConstruction,
  constructionContextChanged,
  constructionRequestCanRestart,
} from "../src/lib/muse-construction-pending.ts";

function recoveryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    values,
  };
}
function originalRequest() {
  return {
    version: 1,
    project_id: "project-one",
    goal: "Hold a phone",
    photo: { id: "photo-one", byte_count: 100, content_type: "image/png" },
    payload: { ...body },
  };
}
test("proposal recovery retains exact original body across remount/reload, scoped to owner and project without credentials", async () => {
  const storage = recoveryStorage();
  const record = originalRequest();
  await retainConstruction("owner-secret", record, storage);
  assert.deepEqual(
    await pendingConstruction("owner-secret", record.project_id, storage),
    record,
  );
  assert.deepEqual(
    await retainConstruction("owner-secret", record, storage),
    record,
  );
  assert.equal(
    await pendingConstruction("different-owner", record.project_id, storage),
    null,
  );
  assert.equal(
    await pendingConstruction("owner-secret", "another-project", storage),
    null,
  );
  assert.ok(!JSON.stringify([...storage.values]).includes("owner-secret"));
  await assert.rejects(
    retainConstruction(
      "owner-secret",
      {
        ...record,
        payload: { ...body, idempotency_key: "different-request" },
      },
      storage,
    ),
    /unresolved/,
  );
  assert.deepEqual(
    await pendingConstruction("owner-secret", record.project_id, storage),
    record,
  );
  await clearConstruction("owner-secret", record, storage);
  assert.equal(
    await pendingConstruction("owner-secret", record.project_id, storage),
    null,
  );
});
test("proposal recovery detects changed context without replacing the original request", () => {
  const record = originalRequest();
  const project = {
    id: record.project_id,
    revision_id: body.expected_revision_id,
    goal: record.goal,
  };
  assert.equal(
    constructionContextChanged(record, project, [record.photo]),
    false,
  );
  assert.equal(
    constructionContextChanged(record, project, [
      record.photo,
      { ...record.photo, id: "unselected-photo" },
    ]),
    false,
  );
  for (const change of [
    { id: "another-project" },
    { revision_id: "new-revision" },
    { goal: "New goal" },
  ])
    assert.equal(
      constructionContextChanged(record, { ...project, ...change }, [
        record.photo,
      ]),
      true,
    );
  for (const photos of [
    [],
    [{ ...record.photo, byte_count: 101 }],
    [{ ...record.photo, content_type: "image/jpeg" }],
  ])
    assert.equal(constructionContextChanged(record, project, photos), true);
});
test("proposal persistence fails closed for unavailable, ineffective or uncleared storage", async () => {
  const record = originalRequest();
  const storage = recoveryStorage();
  await assert.rejects(
    pendingConstruction("owner", record.project_id, {
      ...storage,
      getItem() {
        throw new Error("Storage unavailable");
      },
    }),
    /Storage unavailable/,
  );
  await assert.rejects(
    retainConstruction("owner", record, {
      ...storage,
      setItem() {
        throw new Error("Storage unavailable");
      },
    }),
    /Storage unavailable/,
  );
  await assert.rejects(
    retainConstruction("owner", record, {
      ...storage,
      setItem() {},
    }),
    /did not retain/,
  );
  await retainConstruction("owner", record, storage);
  await assert.rejects(
    clearConstruction("owner", record, {
      ...storage,
      removeItem() {},
    }),
    /could not be cleared/,
  );
  assert.deepEqual(
    await pendingConstruction("owner", record.project_id, storage),
    record,
  );
});
test("proposal recovery rejects malformed, foreign and oversized browser records without overwriting them", async () => {
  const record = originalRequest();
  const storage = recoveryStorage();
  await retainConstruction("owner", record, storage);
  const [key] = storage.values.keys();
  for (const raw of [
    "{",
    " ".repeat(32769),
    JSON.stringify({ ...record, project_id: "foreign" }),
    JSON.stringify({
      ...record,
      payload: { ...body, endpoint: "https://foreign.invalid" },
    }),
  ]) {
    storage.setItem(key, raw);
    await assert.rejects(
      pendingConstruction("owner", record.project_id, storage),
      /cannot be verified|invalid identity/,
    );
    await assert.rejects(retainConstruction("owner", record, storage));
    assert.equal(storage.getItem(key), raw);
    assert.equal(
      await pendingConstruction("foreign-owner", record.project_id, storage),
      null,
    );
  }
});
test("proposal recovery validates request consent, identities, notes and photo metadata", () => {
  assert.equal(validPendingConstruction(originalRequest()), true);
  const withoutPhoto = originalRequest();
  withoutPhoto.photo = null;
  withoutPhoto.payload.media_id = null;
  withoutPhoto.payload.provider_transfer_consented = false;
  assert.equal(validPendingConstruction(withoutPhoto), true);
  for (const change of [
    (r) => {
      r.version = 2;
    },
    (r) => {
      r.payload.provider_context_consented = false;
    },
    (r) => {
      r.payload.provider_transfer_consented = false;
    },
    (r) => {
      r.payload.expected_revision_id = "../foreign";
    },
    (r) => {
      r.payload.idempotency_key = "short";
    },
    (r) => {
      r.payload.user_notes = "x".repeat(1001);
    },
    (r) => {
      r.photo.id = "other-photo";
    },
    (r) => {
      r.photo.byte_count = Infinity;
    },
    (r) => {
      r.photo.byte_count = 0;
    },
    (r) => {
      r.photo.byte_count = 5_000_001;
    },
    (r) => {
      r.photo.content_type = "image/svg+xml";
    },
    (r) => {
      r.goal = "x".repeat(2001);
    },
    (r) => {
      r.credential = "private";
    },
  ]) {
    const record = originalRequest();
    change(record);
    assert.equal(validPendingConstruction(record), false);
  }
});

test("only definitive server rejections permit explicit start-over; invalid local responses remain uncertain", async (t) => {
  let calls = 0;
  let response = new Response(
    JSON.stringify({
      code: "invalid_response",
      message: "private-provider-body",
    }),
    { status: 502 },
  );
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return response;
  });
  await assert.rejects(
    proposeConstruction("owner", "project-one", body),
    (e) =>
      e.code === "proposal_rejected" &&
      constructionRequestCanRestart(e.code) &&
      !e.message.includes("private-provider-body"),
  );
  response = new Response("malformed", { status: 502 });
  await assert.rejects(
    proposeConstruction("owner", "project-one", body),
    (e) =>
      e.code === "invalid_response" && !constructionRequestCanRestart(e.code),
  );
  assert.equal(calls, 2);
  for (const code of [
    "validation_error",
    "consent_required",
    "provider_not_configured",
    "provider_authentication",
    "access_denied",
    "rate_limit",
    "proposal_rejected",
  ])
    assert.equal(constructionRequestCanRestart(code), true);
  for (const code of [
    undefined,
    "timeout",
    "network_error",
    "invalid_response",
    "generation_in_progress",
    "generation_outcome_unknown",
    "cancelled",
    "stale_version",
    "idempotency_conflict",
    "not_found",
    "blocked",
    "provider_error",
  ])
    assert.equal(constructionRequestCanRestart(code), false);
});

test("receipt inspection is authenticated GET only and returns bounded safe fields", async (t) => {
  const receipt = {
    idempotency_key: "original-key",
    digest: "a".repeat(64),
    state: "unknown",
    error_code: "timeout",
  };
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls++;
    assert.equal(url, "/api/projects/project-one/construction/receipts");
    assert.equal(init.method, "GET");
    assert.equal(init.body, undefined);
    assert.equal(init.headers.Authorization, "Bearer owner");
    assert.equal(init.cache, "no-store");
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    return new Response(
      JSON.stringify({
        receipts: [{ ...receipt, raw: "SECRET" }],
        raw: "SECRET",
      }),
    );
  });
  assert.deepEqual(await constructionReceipts("owner", "project-one"), {
    receipts: [receipt],
  });
  assert.equal(calls, 1);
});

test("receipt inspection fails closed without exposing bodies or retrying", async (t) => {
  const receipt = {
    idempotency_key: "original-key",
    digest: "a".repeat(64),
    state: "unknown",
  };
  for (const value of [
    { receipts: [{ ...receipt, error_code: "SECRET" }] },
    { receipts: [{ ...receipt, digest: "SECRET" }] },
    { receipts: Array(17).fill(receipt) },
    { receipts: null },
  ]) {
    let calls = 0;
    t.mock.method(globalThis, "fetch", async () => {
      calls++;
      return new Response(JSON.stringify(value));
    });
    await assert.rejects(
      constructionReceipts("owner", "project-one"),
      (error) =>
        error.code === "receipt_status_unavailable" &&
        !error.message.includes("SECRET"),
    );
    assert.equal(calls, 1);
    t.mock.restoreAll();
  }
  t.mock.method(globalThis, "fetch", async () => {
    throw new Error("SECRET");
  });
  await assert.rejects(constructionReceipts("owner", "project-one"), {
    code: "receipt_status_unavailable",
  });
});

function triangleResult() {
  const vertices = [
    { x: 2, y: 3, z: 4 },
    { x: 2.3, y: 3, z: 4 },
    { x: 2, y: 3.2, z: 4 },
  ];
  const snapshot = {
    project_id: result.project_id,
    inventory_revision: result.inventory_revision_id,
    plan_version_id: "triangle-proposal",
  };
  const facet = {
    facet_id: "triangle-face",
    part_id: "triangle-panel",
    vertices,
    centroid: { x: 2.1, y: 3.0666666667, z: 4 },
    area_fraction: 1,
  };
  return {
    ...result,
    candidates: [
      {
        candidate_id: "triangle-candidate",
        title: "Triangular divider",
        rationale: "Synthetic display check",
        status: "needs_measurement",
        blockers: [],
        estimated_materials: [],
        fabrication_plan: null,
        fabrication_report: null,
        construction: {
          generator_version: "test",
          target_hash: "a".repeat(64),
          limitations: [],
          request: {
            target: {
              assembly: {
                project_id: result.project_id,
                plan_version_id: snapshot.plan_version_id,
                parts: [
                  {
                    part_id: facet.part_id,
                    facets: [
                      { facet_id: facet.facet_id, vertices_local: vertices },
                    ],
                  },
                ],
              },
              snapshot,
            },
          },
          piece_catalog: [
            {
              part_id: facet.part_id,
              reference: "Piece 1",
              display_name: "Triangular divider",
              geometry_class: "triangle",
            },
          ],
          steps: [
            {
              step_id: "place-triangle",
              index: 0,
              action: "place",
              part_ids: [facet.part_id],
              depends_on_step_ids: [],
              instruction: "Position the proposed panel",
              operation_ids: [],
              requires_external_support: true,
              unresolved_predicates: ["Support unknown"],
              analysis: {
                snapshot,
                present_part_ids: [facet.part_id],
                facets: [facet],
              },
            },
          ],
        },
      },
    ],
  };
}

test("saved complete non-stand manual loads through authenticated GET only", async (t) => {
  const saved = triangleResult();
  assert.equal(
    validConstructionResult(
      saved,
      result.project_id,
      result.inventory_revision_id,
    ),
    true,
  );
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls++;
    assert.equal(
      url,
      "/api/projects/project-one/construction/preview?expected_inventory_revision_id=inventory-one",
    );
    assert.equal(init.method, undefined);
    assert.equal(init.headers.Authorization, "Bearer owner");
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.equal(init.cache, "no-store");
    return new Response(JSON.stringify(saved));
  });
  assert.deepEqual(
    await savedConstruction(
      "owner",
      result.project_id,
      result.inventory_revision_id,
    ),
    saved,
  );
  assert.equal(calls, 1);
});

test("saved manual rejects stale, foreign, malformed nested geometry and unknown responses", async (t) => {
  const invalid = [];
  for (const change of [
    (v) => {
      v.inventory_revision_id = "other";
    },
    (v) => {
      v.project_id = "other";
    },
    (v) => {
      v.candidates[0].construction.steps = [];
    },
    (v) => {
      v.candidates[0].construction.steps[0].analysis.facets[0].vertices[0].x =
        null;
    },
    (v) => {
      v.candidates[0].construction.steps[0].analysis.facets[0].part_id =
        "foreign";
    },
    (v) => {
      v.candidates[0].construction.steps[0].analysis.snapshot.inventory_revision =
        "other";
    },
    (v) => {
      v.candidates[0].construction.piece_catalog[0].geometry_class = null;
    },
  ]) {
    const value = triangleResult();
    change(value);
    invalid.push(value);
  }
  for (const value of invalid) {
    t.mock.method(
      globalThis,
      "fetch",
      async () => new Response(JSON.stringify(value)),
    );
    await assert.rejects(
      savedConstruction(
        "owner",
        result.project_id,
        result.inventory_revision_id,
      ),
      { code: "saved_construction_unavailable" },
    );
    t.mock.restoreAll();
  }
  for (const status of [401, 409, 503]) {
    let calls = 0;
    t.mock.method(globalThis, "fetch", async () => {
      calls++;
      return new Response(
        JSON.stringify({
          code: "generation_outcome_unknown",
          message: "PRIVATE",
        }),
        { status },
      );
    });
    await assert.rejects(
      savedConstruction(
        "owner",
        result.project_id,
        result.inventory_revision_id,
      ),
      (e) =>
        e.code === "saved_construction_unavailable" &&
        !e.message.includes("PRIVATE"),
    );
    assert.equal(calls, 1);
    t.mock.restoreAll();
  }
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response("{}", { status: 404 }),
  );
  assert.equal(
    await savedConstruction(
      "owner",
      result.project_id,
      result.inventory_revision_id,
    ),
    null,
  );
});

test("aborted or oversized saved response cannot populate the manual", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (_, init) => {
    controller.abort();
    assert.equal(init.signal.aborted, true);
    return new Response(JSON.stringify(triangleResult()));
  });
  await assert.rejects(
    savedConstruction(
      "owner",
      result.project_id,
      result.inventory_revision_id,
      controller.signal,
    ),
  );
  t.mock.restoreAll();
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(" ".repeat(8_000_001)),
  );
  await assert.rejects(
    savedConstruction("owner", result.project_id, result.inventory_revision_id),
  );
});

test("camera fit is translation invariant, excludes nonfinite facets, and never includes the origin", () => {
  const facets =
    triangleResult().candidates[0].construction.steps[0].analysis.facets;
  for (const [yaw, pitch] of [
    [0, 30],
    [45, 25],
    [180, -30],
    [315, 25],
  ]) {
    const project = constructionCamera(yaw, pitch);
    const shifted = facets.map((f) => ({
      ...f,
      vertices: f.vertices.map((p) => ({
        x: p.x + 17,
        y: p.y - 31,
        z: p.z + 45,
      })),
      centroid: {
        x: f.centroid.x + 17,
        y: f.centroid.y - 31,
        z: f.centroid.z + 45,
      },
    }));
    const normalized = (fs) => {
      const projected = projectConstructionFacets(fs, project);
      const fit = fitConstructionProjection(projected.flatMap((f) => f.points));
      return projected.flatMap((f) =>
        f.points.map((p) => [fit.x(p.x), fit.y(p.y)]),
      );
    };
    const before = normalized(facets),
      after = normalized(shifted);
    before
      .flat()
      .forEach((n, i) => assert.ok(Math.abs(n - after.flat()[i]) < 1e-7));
  }
  const bad = { ...facets[0], centroid: { x: NaN, y: 0, z: 0 } };
  assert.equal(
    projectConstructionFacets([bad], (p) => ({ ...p, depth: p.z })).length,
    0,
  );
  const fit = fitConstructionProjection([]);
  assert.equal(fit.x(0), 200);
});

test("orthographic step diagrams keep canonical triangle identities and metre-to-mm dimensions", () => {
  const step = triangleResult().candidates[0].construction.steps[0];
  for (const view of ["top", "front", "side"]) {
    const projected = orthographicConstruction(step.analysis.facets, view);
    assert.deepEqual(
      projected.facets.map((f) => [f.part_id, f.facet_id, f.points.length]),
      [["triangle-panel", "triangle-face", 3]],
    );
    assert.equal(step.part_ids.includes(projected.facets[0].part_id), true);
    assert.ok(
      Math.abs(projected.fit.width * 1000 - (view === "side" ? 200 : 300)) <
        1e-8,
    );
    assert.ok(
      Math.abs(projected.fit.height * 1000 - (view === "top" ? 200 : 0)) < 1e-8,
    );
  }
});

test("positive camera elevation paints near panels after far panels on the same viewing ray", () => {
  const project = constructionCamera(0, 30);
  const ray = { x: 0, y: -Math.sqrt(3) / 2, z: 0.5 };
  const far =
    triangleResult().candidates[0].construction.steps[0].analysis.facets[0];
  const towardViewer = (p) => ({
    x: p.x + ray.x,
    y: p.y + ray.y,
    z: p.z + ray.z,
  });
  const near = {
    ...far,
    part_id: "near-panel",
    facet_id: "near-face",
    vertices: far.vertices.map(towardViewer),
    centroid: towardViewer(far.centroid),
  };
  const original = structuredClone([near, far]);
  const facets = projectConstructionFacets([near, far], project);
  facets[0].points.forEach((p, index) => {
    const behind = facets[1].points[index];
    assert.ok(Math.abs(p.x - behind.x) < 1e-10);
    assert.ok(Math.abs(p.y - behind.y) < 1e-10);
    assert.ok(Math.abs(p.depth - behind.depth - 1) < 1e-10);
  });
  assert.deepEqual(
    facets
      .sort((a, b) => a.center.depth - b.center.depth)
      .map((f) => f.part_id),
    [far.part_id, near.part_id],
  );
  assert.deepEqual(
    [near, far],
    original,
    "camera never changes canonical panels",
  );
});

test("orthographic near panels paint last: front negative Y, top positive Z, side positive X", () => {
  const base =
    triangleResult().candidates[0].construction.steps[0].analysis.facets[0];
  for (const [view, towardViewer] of [
    ["front", (p) => ({ ...p, y: p.y - 1 })],
    ["top", (p) => ({ ...p, z: p.z + 1 })],
    ["side", (p) => ({ ...p, x: p.x + 1 })],
  ]) {
    const near = {
      ...base,
      part_id: "near-panel",
      facet_id: "near-face",
      vertices: base.vertices.map(towardViewer),
      centroid: towardViewer(base.centroid),
    };
    const { facets } = orthographicConstruction([near, base], view);
    facets[0].points.forEach((p, index) => {
      assert.equal(p.x, facets[1].points[index].x);
      assert.equal(p.y, facets[1].points[index].y);
      assert.ok(Math.abs(p.depth - facets[1].points[index].depth - 1) < 1e-10);
    });
    assert.deepEqual(
      facets
        .sort((a, b) => a.center.depth - b.center.depth)
        .map((f) => f.part_id),
      [base.part_id, near.part_id],
    );
  }
});

test("replacement authorization is an explicit separate POST with exact binding and no generation", async (t) => {
  const body = {
    expected_revision_id: "inventory-one",
    original_idempotency_key: "original-key",
    original_digest: "a".repeat(64),
    replacement_idempotency_key: "replacement-key",
    acknowledge_unknown: true,
  };
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls++;
    assert.equal(
      url,
      "/api/projects/project-one/construction/replacement-authorizations",
    );
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), body);
    return new Response(
      JSON.stringify({ ...body, project_id: "project-one", replayed: false }),
    );
  });
  assert.equal(
    (await authorizeConstructionReplacement("owner", "project-one", body))
      .replacement_idempotency_key,
    "replacement-key",
  );
  assert.equal(calls, 1);
  t.mock.restoreAll();
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({ ...body, project_id: "other", replayed: false }),
      ),
  );
  await assert.rejects(
    authorizeConstructionReplacement("owner", "project-one", body),
  );
});

test("authorized ancestry permits only its exact successor and a new unknown child blocks again", () => {
  const original = {
    idempotency_key: "original-key",
    digest: "a".repeat(64),
    state: "unknown",
    error_code: "timeout",
    replacement_idempotency_key: "replacement-key",
    replacement_expected_revision_id: "inventory-one",
  };
  assert.equal(blockingConstructionReceipts([original]).length, 1);
  assert.equal(
    blockingConstructionReceipts([original], "unrelated-key", "inventory-one")
      .length,
    1,
  );
  assert.equal(
    blockingConstructionReceipts([original], "replacement-key", "other").length,
    1,
  );
  assert.equal(
    blockingConstructionReceipts([original], "replacement-key", "inventory-one")
      .length,
    0,
  );
  const child = {
    idempotency_key: "replacement-key",
    digest: "b".repeat(64),
    state: "completed",
    replaces_idempotency_key: "original-key",
  };
  assert.equal(
    blockingConstructionReceipts([child, original]).length,
    0,
    "completed successor leaves its ancestor historical without rewriting it",
  );
  assert.equal(
    blockingConstructionReceipts([child, original], undefined, undefined, true)
      .length,
    0,
  );
  assert.equal(
    blockingConstructionReceipts(
      [child, original],
      "replacement-key",
      "inventory-one",
    ).length,
    0,
  );
  assert.deepEqual(
    blockingConstructionReceipts(
      [{ ...child, state: "unknown" }, original],
      "replacement-key",
      "inventory-one",
    ),
    [{ ...child, state: "unknown" }],
  );
  assert.equal(
    blockingConstructionReceipts([
      { ...child, replaces_idempotency_key: "foreign" },
      original,
    ]).length,
    1,
  );
  assert.equal(original.state, "unknown");
});

test("replacement preserves exact original browser payload before selecting new identity", async () => {
  const storage = recoveryStorage(),
    original = originalRequest();
  await retainConstruction("owner", original, storage);
  const replacement = {
    ...original,
    payload: {
      ...original.payload,
      idempotency_key: "replacement-key",
      user_notes: "New separate proposal",
    },
  };
  await retainReplacementConstruction(
    "owner",
    original.payload.idempotency_key,
    replacement,
    storage,
  );
  assert.equal(storage.values.size, 2);
  const archived = [...storage.values.entries()].find(([key]) =>
    key.includes(":unknown:"),
  );
  assert.equal(archived[1], JSON.stringify(original));
  assert.deepEqual(
    await pendingConstruction("owner", original.project_id, storage),
    replacement,
  );
  assert.deepEqual(
    await retainReplacementConstruction(
      "owner",
      original.payload.idempotency_key,
      {
        ...replacement,
        payload: { ...replacement.payload, user_notes: "Changed draft" },
      },
      storage,
    ),
    replacement,
  );
  await clearConstruction("owner", replacement, storage);
  assert.equal(storage.getItem(archived[0]), JSON.stringify(original));
  assert.equal(
    await pendingConstruction("owner", original.project_id, storage),
    null,
  );
});

test("failed original archive never overwrites the retained unknown request", async () => {
  const storage = recoveryStorage(),
    original = originalRequest();
  await retainConstruction("owner", original, storage);
  const set = storage.setItem;
  storage.setItem = (key, value) => {
    if (!key.includes(":unknown:")) set(key, value);
  };
  await assert.rejects(
    retainReplacementConstruction(
      "owner",
      original.payload.idempotency_key,
      {
        ...original,
        payload: { ...original.payload, idempotency_key: "replacement-key" },
      },
      storage,
    ),
  );
  assert.deepEqual(
    await pendingConstruction("owner", original.project_id, storage),
    original,
  );
});
