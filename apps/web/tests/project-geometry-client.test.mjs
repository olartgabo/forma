import assert from "node:assert/strict";
import { test } from "node:test";
import { loadProjectGeometry } from "../src/lib/project-geometry-client.ts";

const project = {
  id: "saved-project",
  revision_id: "revision",
  goal: "A saved design",
  active_version_id: null,
};
const facets = [
  {
    facet_id: "panel",
    part_id: "part",
    vertices: [
      { x: 0, y: 0, z: 0 },
      { x: 1, y: 0, z: 0 },
      { x: 0, y: 1, z: 0 },
    ],
  },
];
function manual(version = "newest") {
  return {
    project_id: project.id,
    version_id: version,
    inventory_revision_id: project.revision_id,
    plan: { project_id: project.id, version_id: version },
    manual: {
      project_id: project.id,
      version_id: version,
      panels: [{ svg: '<svg xmlns="http://www.w3.org/2000/svg"/>' }],
    },
  };
}
function mockReads(t, responses) {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    const next = responses.shift();
    assert.ok(next, "unexpected additional read");
    return {
      ok: next.status === 200,
      status: next.status,
      json: async () => next.body,
    };
  });
  return calls;
}
const load = (p = project) =>
  loadProjectGeometry("private-token", p, new AbortController().signal);

test("native generic facets use secure single bounded read", async (t) => {
  const calls = mockReads(t, [
    {
      status: 200,
      body: {
        project_id: project.id,
        inventory_revision_id: project.revision_id,
        candidates: [
          {
            status: "needs_measurement",
            construction: {
              target_hash: "a".repeat(64),
              steps: [{ analysis: { facets } }],
            },
          },
        ],
      },
    },
  ]);
  assert.deepEqual(await load(), { facets });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
});

test("unknown provider outcomes and authorization failures never discover older plans", async (t) => {
  const calls = mockReads(
    t,
    [401, 409, 422].map((status) => ({ status })),
  );
  for (let i = 0; i < 3; i++) assert.equal(await load(), null);
  assert.equal(calls.length, 3);
});

test("inactive legacy preview reads newest same revision saved manual", async (t) => {
  const summary = (version_id, created_at, extra = {}) => ({
    project_id: project.id,
    inventory_revision_id: project.revision_id,
    version_id,
    created_at,
    ...extra,
  });
  const calls = mockReads(t, [
    { status: 404 },
    {
      status: 200,
      body: {
        plans: [
          summary("older", "2026-11-01"),
          summary("foreign", "2026-11-04", { project_id: "other" }),
          summary("stale", "2026-11-04", { inventory_revision_id: "old" }),
          summary("newest", "2026-11-03"),
        ],
      },
    },
    { status: 200, body: manual() },
  ]);
  assert.deepEqual(await load(), { svg: manual().manual.panels[0].svg });
  assert.equal(calls.length, 3);
  assert.ok(calls[2].url.endsWith("/versions/newest"));
});

test("saved SVG fallback rejects foreign nested plan identity", async (t) => {
  const value = manual();
  value.plan.project_id = "foreign";
  mockReads(t, [{ status: 422 }, { status: 200, body: value }]);
  assert.equal(await load({ ...project, active_version_id: "newest" }), null);
});

test("empty drafts and malformed or blocked candidates stay unavailable", async (t) => {
  mockReads(t, [
    { status: 404 },
    { status: 200, body: { plans: [] } },
    {
      status: 200,
      body: {
        project_id: project.id,
        inventory_revision_id: project.revision_id,
        candidates: [null, { status: "blocked", construction: {} }],
      },
    },
  ]);
  assert.equal(await load(), null);
  assert.equal(await load(), null);
});
