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
  uncertainConstructionOutcome,
} from "../src/lib/muse-construction-client.ts";

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
