import test from "node:test";
import assert from "node:assert/strict";
import { parseArgs, checkStatus } from "./run.mjs";

test("only explicit bounded task/workspace arguments, no resume or shell injection flags", () => {
  assert.deepEqual(parseArgs(["--workspace", "w", "--task-file", "t"]), {
    workspace: "w",
    taskFile: "t",
  });
  for (const args of [
    [],
    ["--workspace", "w"],
    ["--continue", "x"],
    ["--workspace", "w", "--task-file", "t", "--session", "s"],
    ["--workspace", "w", "--workspace", "z", "--task-file", "t"],
  ])
    assert.throws(() => parseArgs(args));
});

test("preserves shared cap, reservation headroom, STOP, pending and expiry gates", () => {
  const state = {
    cap: 90_000_000,
    combinedSpent: 61_000_000,
    pending: 0,
    halted: false,
    expires: "2099-01-01",
  };
  checkStatus(state, false);
  assert.throws(() => checkStatus(state, true));
  for (const patch of [
    { pending: 1 },
    { halted: true },
    { cap: 5_000_000 },
    { combinedSpent: 84_000_001 },
    { combinedSpent: -1 },
    { expires: "invalid" },
    { expires: "2000-01-01" },
  ])
    assert.throws(() => checkStatus({ ...state, ...patch }, false));
});
