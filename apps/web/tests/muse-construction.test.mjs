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

import {
  pendingConstruction,
  retainConstruction,
  clearConstruction,
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
