import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ApiError,
  loadFabricationReport,
  loadPreviewFabricationReport,
  assessFabricationReport,
} from "../src/lib/api.ts";
import {
  orderText,
  readinessGroups,
  toolText,
} from "../src/lib/fabrication-report.ts";

const token = "synthetic-token-0123456789";

function readiness(operation_id, status, extra = {}) {
  return {
    operation_id,
    operation_type: "tape_joint",
    status,
    completed_in_version_id: status === "completed" ? "version-a" : null,
    waiting_on_operation_ids: [],
    blockers: [],
    tools: [],
    required_confirmations: [],
    next_state_id: status === "ready" ? `state-${operation_id}` : null,
    ...extra,
  };
}

function report(overrides = {}) {
  return {
    snapshot: {
      project_id: "project-a",
      version_id: "version-a",
      inventory_revision_id: "inventory-a",
      last_event_id: null,
      plan_sha256: "0".repeat(64),
      history_sha256: "1".repeat(64),
      process_sha256: "2".repeat(64),
      inputs_sha256: "3".repeat(64),
      rules_version: "fabrication-rules-v1",
      compiler_version: "synthetic",
    },
    status: "ready",
    current_state_id: "state-current",
    attached_joint_ids: [],
    damaged_part_ids: [],
    failed_operation_ids: [],
    next_operation_id: "fold",
    operations: [
      readiness("cut", "completed"),
      readiness("fold", "ready"),
      readiness("join", "blocked", {
        blockers: [
          {
            code: "invalid_order",
            message: "Do fold first.",
            target_ids: ["join", "fold"],
          },
        ],
      }),
      readiness("test", "waiting", { waiting_on_operation_ids: ["join"] }),
    ],
    supported_order: [
      { operation_id: "fold", state_id: "state-1", reordered: false },
      { operation_id: "join", state_id: "state-2", reordered: true },
      { operation_id: "test", state_id: "state-3", reordered: false },
    ],
    order_status: "complete",
    order_blockers: [],
    blockers: [],
    access_basis: "declared_rules",
    observed_usability: "not_assessed",
    ...overrides,
  };
}

test("report groups separate the next step from blocked and waiting steps", () => {
  const groups = readinessGroups(report());
  assert.equal(groups.next.operation_id, "fold");
  assert.deepEqual(
    groups.blocked.map((o) => o.operation_id),
    ["join"],
  );
  assert.deepEqual(
    groups.waiting.map((o) => o.operation_id),
    ["test"],
  );
  assert.equal(groups.completed, 1);
  assert.match(orderText(report()), /1 of 3 remaining steps move earlier/);
  assert.match(
    orderText(report({ order_status: "cycle", order_blockers: [{}] })),
    /wait on each other/,
  );
  assert.equal(
    toolText({
      tool: "ruler",
      status: "declared",
      declared_name: "Metal ruler",
    }),
    "Ruler: your saved Metal ruler",
  );
  assert.equal(
    toolText({
      tool: "cutting_tool",
      status: "not_declared",
      declared_name: null,
    }),
    "Cutting tool: not in your saved tools",
  );
});

test("fabrication reports are read-only, owner scoped and identity checked", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(report());
  });
  const loaded = await loadFabricationReport(token, "project-a", "version-a");
  assert.equal(loaded.next_operation_id, "fold");
  assert.equal(
    calls[0].path,
    "/api/projects/project-a/versions/version-a/fabrication",
  );
  assert.equal(calls[0].options.method, "GET");
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.redirect, "error");

  await loadPreviewFabricationReport(
    token,
    "project-a",
    "preview/1",
    "version-a",
  );
  assert.equal(
    calls[1].path,
    "/api/projects/project-a/adapt/previews/preview%2F1/fabrication",
  );

  await assert.rejects(
    loadFabricationReport(token, "project-a", "version-b"),
    (error) => error instanceof ApiError && error.code === "invalid_response",
  );
});

test("stale fabrication reports explain how to recover", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "stale_version", message: "server text", blockers: [] },
      { status: 409 },
    ),
  );
  await assert.rejects(
    loadFabricationReport(token, "project-a", "version-a"),
    (error) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.code === "stale_version" &&
      /Reload the manual/.test(error.message) &&
      !error.message.includes("server text"),
  );
  await assert.rejects(
    loadPreviewFabricationReport(token, "project-a", "preview-1", "version-a"),
    (error) =>
      error instanceof ApiError &&
      /Simulate the repair again/.test(error.message),
  );
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "blocked", message: "private server text" },
      { status: 409 },
    ),
  );
  await assert.rejects(
    loadFabricationReport(token, "project-a", "version-a"),
    (error) =>
      error instanceof ApiError &&
      /supported report limits/.test(error.message) &&
      !error.message.includes("private server text"),
  );
});

test("fresh confirmations are read-only, scoped to exact inventory/history and never echo rejected server text", async (t) => {
  const calls = [];
  const body = {
    expected_inventory_revision_id: "inventory-a",
    expected_last_event_id: null,
    additional_tools: ["scissors"],
    tools_confirmed: true,
  };
  t.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return Response.json(report());
  });
  await assessFabricationReport(token, "project-a", "version-a", body);
  assert.equal(
    calls[0].path,
    "/api/projects/project-a/versions/version-a/fabrication/assess",
  );
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(
    calls[0].options.headers.get("Authorization"),
    `Bearer ${token}`,
  );
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
  await assert.rejects(
    assessFabricationReport(token, "project-a", "version-a", {
      ...body,
      expected_last_event_id: "old-cursor",
    }),
    (error) => error instanceof ApiError && error.code === "invalid_response",
  );
  await assert.rejects(
    assessFabricationReport(token, "project-a", "version-a", {
      ...body,
      expected_inventory_revision_id: "old-inventory",
    }),
    (error) => error instanceof ApiError && error.code === "invalid_response",
  );
  t.mock.method(globalThis, "fetch", async () =>
    Response.json(
      { code: "validation_error", message: "private server text" },
      { status: 422 },
    ),
  );
  await assert.rejects(
    assessFabricationReport(token, "project-a", "version-a", body),
    (error) =>
      error instanceof ApiError &&
      /material loss/.test(error.message) &&
      !error.message.includes("private server text"),
  );
});
