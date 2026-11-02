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
import { mkdtempSync, existsSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

test("legacy CLI always stops before settings, process or network access", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "forma-retired-"));
  const marker = path.join(home, "forbidden-access");
  const preload = path.join(home, "trap.cjs");
  writeFileSync(
    preload,
    `
    const fs = require("node:fs");
    const child = require("node:child_process");
    const net = require("node:net");
    const http = require("node:http");
    const https = require("node:https");
    const marker = ${JSON.stringify(marker)};
    const record = (name) => { fs.appendFileSync(marker, name); throw Error("forbidden " + name); };
    const read = fs.readFileSync;
    fs.readFileSync = function (file, ...args) {
      if (String(file).includes("settings.json") || String(file).includes("opencode.json")) record("settings");
      return read.call(this, file, ...args);
    };
    for (const name of ["spawn", "spawnSync", "execFile", "execFileSync", "exec", "execSync", "fork"]) child[name] = () => record("process");
    net.connect = net.createConnection = () => record("network");
    http.request = http.get = https.request = https.get = () => record("network");
    global.fetch = () => record("network");
    require("node:module").syncBuiltinESMExports();
  `,
  );
  try {
    const launcher = fileURLToPath(new URL("./run.mjs", import.meta.url));
    for (const args of [
      [],
      ["--workspace", "unused", "--task-file", "unused"],
    ]) {
      const child = spawn(
        process.execPath,
        ["--require", preload, launcher, ...args],
        {
          env: { ...process.env, META_GUARD_HOME: home },
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
      let output = "";
      child.stdout.on("data", (chunk) => {
        output += chunk;
      });
      child.stderr.on("data", (chunk) => {
        output += chunk;
      });
      const code = await new Promise((resolve, reject) =>
        child.once("error", reject).once("exit", resolve),
      );
      assert.equal(code, 1);
      assert.match(output, /retired.*native Codex Sol\/Terra.*Sonnet/i);
      assert.doesNotMatch(output, /settings\.json|ENOENT|forbidden/);
      assert.equal(existsSync(marker), false);
    }
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
