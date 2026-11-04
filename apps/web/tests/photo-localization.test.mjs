import assert from "node:assert/strict";
import { test } from "node:test";
import {
  localizePhoto,
  validPhotoBox,
  validLocalizationRequest,
} from "../src/lib/photo-localization.ts";
const photo = { id: "photo-1", width_px: 12, height_px: 8 };
const box = {
  label: "cardboard",
  source: "sam",
  x1: 1,
  y1: 2,
  x2: 9,
  y2: 6,
  width: 12,
  height: 8,
};
const body = {
  media_id: photo.id,
  expected_revision_id: "revision-1",
  concept: "cardboard",
  provider_transfer_consented: true,
  idempotency_key: "request-1",
};
const result = {
  project_id: "project-1",
  revision_id: "revision-1",
  media_id: photo.id,
  width_px: 12,
  height_px: 8,
  boxes: [box],
  model: "sam-3.1",
  usage: { model_calls: 1, input_tokens: null, output_tokens: null },
  physical_status: "unverified_photo_annotation",
  replayed: false,
};
test("source pixels reject frames, bounds, labels and nonintegral coordinates", () => {
  assert(validPhotoBox(box, photo, "cardboard"));
  for (const change of [
    { width: 13 },
    { x2: 12 },
    { x1: -1 },
    { y1: 7 },
    { x1: 1.5 },
    { label: "" },
    { source: "measured" },
  ])
    assert(!validPhotoBox({ ...box, ...change }, photo, "cardboard"));
});
test("request preserves exact consented body and validates the whole result", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push([url, options]);
    return new Response(JSON.stringify(result));
  };
  try {
    assert.deepEqual(
      await localizePhoto("private-token", "project-1", photo, body),
      result,
    );
    assert.equal(requests[0][0], "/api/projects/project-1/photo-localizations");
    assert.equal(requests[0][1].headers.Authorization, "Bearer private-token");
    assert.deepEqual(JSON.parse(requests[0][1].body), body);
    for (const change of [
      { project_id: "foreign" },
      { revision_id: "stale" },
      { media_id: "wrong" },
      { width_px: 13 },
      { boxes: [{ ...box, label: "wrong" }] },
      { boxes: [{ ...box, x2: 12 }] },
      { usage: { model_calls: "1" } },
      { physical_status: "confirmed" },
      { replayed: "true" },
    ]) {
      globalThis.fetch = async () =>
        new Response(JSON.stringify({ ...result, ...change }));
      await assert.rejects(
        localizePhoto("private-token", "project-1", photo, body),
        (error) => error.code === "unknown",
      );
    }
  } finally {
    globalThis.fetch = original;
  }
});
test("unreadable, pending and unknown outcomes retain uncertainty instead of requesting again", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    for (const [text, status, code] of [
      ["broken", 200, "unknown"],
      [
        JSON.stringify({ code: "generation_in_progress", message: "pending" }),
        409,
        "generation_in_progress",
      ],
      [
        JSON.stringify({
          code: "generation_outcome_unknown",
          message: "unknown",
        }),
        409,
        "generation_outcome_unknown",
      ],
    ]) {
      globalThis.fetch = async () => {
        calls++;
        return new Response(text, { status });
      };
      await assert.rejects(
        localizePhoto("token", "project-1", photo, body),
        (e) => e.code === code,
      );
    }
    assert.equal(calls, 3);
  } finally {
    globalThis.fetch = original;
  }
});

test("durable receipts are owner/project scoped and reject changed or corrupt exact bodies", async () => {
  const { receipts } =
    await import("../src/components/design-candidates/pending.ts");
  const saved = new Map();
  const storage = {
    getItem: (k) => saved.get(k) ?? null,
    setItem: (k, v) => saved.set(k, v),
    removeItem: (k) => saved.delete(k),
  };
  const store = receipts("sam-test:", validLocalizationRequest, "SAM request");
  assert(validLocalizationRequest(body));
  for (const value of [
    { ...body, provider_transfer_consented: false },
    { ...body, concept: " " },
    { ...body, extra: true },
    { ...body, media_id: "../foreign" },
  ])
    assert(!validLocalizationRequest(value));
  await store.retain("owner-one", "project-1", body, storage);
  assert.deepEqual(
    await store.pending("owner-one", "project-1", storage),
    body,
  );
  assert.equal(await store.pending("owner-two", "project-1", storage), null);
  assert.equal(await store.pending("owner-one", "project-2", storage), null);
  assert(![...saved.keys()][0].includes("owner-one"));
  await assert.rejects(
    store.retain(
      "owner-one",
      "project-1",
      { ...body, concept: "tape" },
      storage,
    ),
  );
  await store.clear("owner-one", "project-1", body, storage);
  assert.equal(saved.size, 0);
  await store.retain("owner-one", "project-1", body, storage);
  saved.set([...saved.keys()][0], "broken");
  await assert.rejects(store.pending("owner-one", "project-1", storage));
});
