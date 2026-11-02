import assert from "node:assert/strict";
import { test } from "node:test";
import { loadPhotoPreview } from "../src/lib/photo-preview-loader.ts";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function environment(decode) {
  const revoked = [];
  const images = [];
  let next = 0;
  return {
    revoked,
    images,
    createObjectURL: () => `blob:preview-${++next}`,
    revokeObjectURL: (url) => revoked.push(url),
    createImage: () => {
      const image = { src: "", decode };
      images.push(image);
      return image;
    },
  };
}

const fetchBlob = async () => new Blob(["photo"]);

test("decode failure releases its URL and a fresh retry can succeed", async () => {
  let attempts = 0;
  const env = environment(async () => {
    if (++attempts === 1) throw new Error("invalid image bytes");
  });
  await assert.rejects(
    loadPhotoPreview(fetchBlob, new AbortController().signal, env),
    /invalid image bytes/,
  );
  assert.deepEqual(env.revoked, ["blob:preview-1"]);
  const preview = await loadPhotoPreview(
    fetchBlob,
    new AbortController().signal,
    env,
  );
  assert.equal(preview.url, "blob:preview-2");
  assert.equal(env.images[1].src, preview.url);
  preview.dispose();
  preview.dispose();
  assert.deepEqual(env.revoked, ["blob:preview-1", "blob:preview-2"]);
});

test("project change during decode releases old URL and cannot return old preview", async () => {
  const decode = deferred();
  const old = new AbortController();
  const env = environment(() => decode.promise);
  const stale = loadPhotoPreview(fetchBlob, old.signal, env);
  await Promise.resolve();
  old.abort();
  assert.deepEqual(env.revoked, ["blob:preview-1"]);
  decode.resolve();
  await assert.rejects(stale, { name: "AbortError" });
  const freshEnv = environment(async () => {});
  const fresh = await loadPhotoPreview(
    fetchBlob,
    new AbortController().signal,
    freshEnv,
  );
  assert.deepEqual(freshEnv.revoked, []);
  fresh.dispose();
  assert.deepEqual(env.revoked, ["blob:preview-1"]);
});

test("unmount before a delayed fetch finishes never allocates a URL", async () => {
  const fetch = deferred();
  const controller = new AbortController();
  const env = environment(async () => {});
  const pending = loadPhotoPreview(() => fetch.promise, controller.signal, env);
  controller.abort();
  fetch.resolve(new Blob(["late photo"]));
  await assert.rejects(pending, { name: "AbortError" });
  assert.deepEqual(env.images, []);
  assert.deepEqual(env.revoked, []);
});

test("network failure creates no preview resource", async () => {
  const env = environment(async () => {});
  await assert.rejects(
    loadPhotoPreview(
      async () => {
        throw new Error("offline");
      },
      new AbortController().signal,
      env,
    ),
    /offline/,
  );
  assert.deepEqual(env.images, []);
  assert.deepEqual(env.revoked, []);
});

test("successful mounted preview remains owned until cleanup", async () => {
  const env = environment(async () => {});
  const controller = new AbortController();
  const preview = await loadPhotoPreview(fetchBlob, controller.signal, env);
  assert.deepEqual(env.revoked, []);
  controller.abort();
  preview.dispose();
  assert.deepEqual(env.revoked, [preview.url]);
});
