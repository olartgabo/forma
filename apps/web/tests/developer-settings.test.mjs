import assert from "node:assert/strict";
import { test } from "node:test";
import { modelKeyHeaders, setModelKey } from "../src/lib/developer-settings.ts";
test("BYOK headers are absent until configured and disappear when cleared", () => {
  assert.deepEqual(modelKeyHeaders(), {});
  setModelKey("test-only-provider-value");
  assert.deepEqual(modelKeyHeaders(), {
    "X-Forma-Model-Key": "test-only-provider-value",
  });
  setModelKey("");
  assert.deepEqual(modelKeyHeaders(), {});
});
