import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  workerConfig,
  workerPrompt,
  validateTask,
  CHECKS,
} from "./worker-policy.mjs";
const task = {
  goal: "Fix one feature",
  acceptance_criteria: ["Regression fails before and passes after"],
  files_allowed: [
    "packages/renderer/src/forma_renderer/svg.py",
    "packages/renderer/tests/test_svg.py",
  ],
};
test("Muse receives both code and tests, exact offline checks, bounded compaction", (t) => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "muse-policy-"));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  const base = {
    model: "meta_guard/muse-wonder-1.0",
    permission: { bash: "ask" },
  };
  const config = workerConfig(base, workspace, task);
  assert.equal(config.permission.edit[task.files_allowed[1]], "allow");
  assert.equal(config.permission.edit["*"], "deny");
  assert.equal(config.permission.bash["*"], "deny");
  for (const cmd of CHECKS) assert.equal(config.permission.bash[cmd], "allow");
  assert.equal(config.permission.bash["git push"], undefined);
  assert.equal(config.permission.task, "deny");
  assert.deepEqual(config.compaction, {
    auto: true,
    prune: true,
    reserved: 10000,
  });
  assert.equal(base.permission.bash, "ask");
  assert.equal(config.model, base.model);
});
test("reject a junction or symlink that redirects permitted writes outside workspace", (t) => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "muse-policy-link-"));
  t.after(() => fs.rmSync(fixture, { recursive: true, force: true }));
  const workspace = path.join(fixture, "workspace"),
    outside = path.join(fixture, "outside");
  fs.mkdirSync(path.join(workspace, "packages/renderer"), { recursive: true });
  fs.mkdirSync(outside);
  fs.symlinkSync(
    outside,
    path.join(workspace, "packages/renderer/tests"),
    process.platform === "win32" ? "junction" : "dir",
  );
  assert.throws(() => workerConfig({}, workspace, task), /escapes/);
});
test("reject production-only tasks, traversal, glob and secret edit scopes", () => {
  for (const files of [
    [task.files_allowed[0]],
    ["packages/renderer/tests/../../guard.mjs"],
    ["packages/renderer/tests/*.py"],
    ["packages/renderer/tests/.env"],
    ["C:/outside/test_x.py"],
  ])
    assert.throws(() => validateTask({ ...task, files_allowed: files }));
});
test("handoff is small and retains repair limits rather than transcripts", () => {
  assert.match(workerPrompt(task), /TWO unsuccessful repair attempts/);
  assert.match(workerPrompt(task), /READY_FOR_FINAL_REVIEW/);
  assert.throws(() => workerPrompt(task, "x".repeat(16000)), /16KB/);
});
