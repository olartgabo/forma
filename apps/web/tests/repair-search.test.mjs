import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, searchRepairs } from "../src/lib/api.ts";
import { candidateText, searchStatusText } from "../src/lib/repair-search.ts";

const token = "synthetic-token-0123456789";

function patch(kind, extra = {}) {
  return {
    id: `search-${kind}`,
    base_version_id: "version-a",
    kind,
    target_id: "stand-brace",
    replacement_stock_id: null,
    replacement_profile_id: null,
    width_mm: null,
    height_mm: null,
    angle_deg: null,
    rationale: "SYNTHETIC",
    ...extra,
  };
}

function summary(status, evaluated = 2, generated = 3) {
  return {
    search_version: "repair-search-v1",
    status,
    target_ids: ["stand-brace"],
    generated_count: generated,
    evaluated_count: evaluated,
    limits: { max_evaluated: evaluated, max_results: 3 },
    outcomes: [],
    unknown_cost_terms: ["time", "purchase_price", "strength"],
    stability_coverage: "unverified",
  };
}

test("search status separates found, exhausted and infeasible", () => {
  assert.match(searchStatusText(summary("found")), /Checked 2 of 3/);
  assert.match(
    searchStatusText(summary("exhausted")),
    /search limit.*unchecked candidates might/,
  );
  assert.match(
    searchStatusText(summary("infeasible", 3, 3)),
    /Checked all 3 .* None passed/,
  );
  assert.match(
    searchStatusText(summary("infeasible", 0, 0)),
    /No candidate repair can be built/,
  );
});

test("each candidate names its operator and why it did or did not pass", () => {
  assert.equal(
    candidateText({
      patch: patch("replace_part", { replacement_stock_id: "spare" }),
      status: "ranked",
      rank: 1,
      preview_id: "preview-1",
      blockers: [],
    }),
    "Replace stand-brace from spare: passed, rank 1",
  );
  assert.equal(
    candidateText({
      patch: patch("replace_joint_profile", {
        target_id: "stand-joint-rear",
        replacement_profile_id: "fold-profile",
      }),
      status: "infeasible",
      rank: null,
      preview_id: null,
      blockers: [],
    }),
    "Join stand-joint-rear with fold-profile: did not pass",
  );
  assert.match(
    candidateText({
      patch: patch("replace_part", { replacement_stock_id: "spare" }),
      status: "ranked",
      rank: 4,
      preview_id: null,
      blockers: [],
    }),
    /not previewed/,
  );
});

test("search posts to the owner-scoped route and explains conflicts locally", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return calls.length === 1
      ? Response.json({
          summary: summary("found"),
          previews: {},
          replayed: false,
        })
      : Response.json(
          { code: "blocked", message: "server text", blockers: [] },
          { status: 409 },
        );
  });
  const body = {
    expected_version_id: "version-a",
    expected_last_event_id: null,
    idempotency_key: "search-key-0001",
    target_ids: [],
    connector_measurements: [],
    remaining_confirmed: true,
  };
  await searchRepairs(token, "project/a", body);
  assert.equal(calls[0].path, "/api/projects/project%2Fa/repairs/search");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
  assert.equal(calls[0].options.cache, "no-store");
  await assert.rejects(
    searchRepairs(token, "project-a", body),
    (error) =>
      error instanceof ApiError &&
      error.status === 409 &&
      /nothing to search for yet/.test(error.message) &&
      !error.message.includes("server text"),
  );
});
