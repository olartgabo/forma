import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export function parseArgs(args) {
  const result = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = { "--workspace": "workspace", "--task-file": "taskFile" }[
      args[i]
    ];
    if (!key || result[key] || !args[i + 1] || args[i + 1].startsWith("--"))
      throw Error("Use --workspace <worktree> --task-file <task.json>");
    result[key] = args[i + 1];
  }
  if (!result.workspace || !result.taskFile)
    throw Error("Workspace and task file are required");
  return result;
}

export function workspaceRoot(input) {
  const workspace = fs.realpathSync(input);
  const query = (...args) =>
    execFileSync("git", ["-C", workspace, ...args], {
      encoding: "utf8",
      windowsHide: true,
    }).trim();
  if (
    fs.realpathSync(query("rev-parse", "--show-toplevel")).toLowerCase() !==
    workspace.toLowerCase()
  )
    throw Error("Workspace must be the exact repository root");
  if (
    !/^(https:\/\/github\.com\/olartgabo\/forma(?:\.git)?|git@github\.com:olartgabo\/forma(?:\.git)?)\/?$/i.test(
      query("remote", "get-url", "origin"),
    )
  )
    throw Error("Only the FORMA repository is allowed");
  if (!query("branch", "--show-current").startsWith("agent/muse-"))
    throw Error("Use a dedicated agent/muse- branch");
  const registered = query("worktree", "list", "--porcelain")
    .split("\n")
    .filter((x) => x.startsWith("worktree "))
    .map((x) => fs.realpathSync(x.slice(9)).toLowerCase());
  if (!registered.includes(workspace.toLowerCase()))
    throw Error("Workspace must be registered with Git");
  if (query("status", "--porcelain"))
    throw Error("Preserve existing edits: start from a clean, owned worktree");
  return workspace;
}

export function checkStatus(state, stopped, now = Date.now()) {
  if (
    stopped ||
    state.halted ||
    state.pending !== 0 ||
    !Number.isFinite(Date.parse(state.expires)) ||
    now >= Date.parse(state.expires)
  )
    throw Error(
      "Guard paused: STOP, pending usage or expired billing verification",
    );
  if (
    !Number.isSafeInteger(state.cap) ||
    state.cap < 6_000_000 ||
    !Number.isSafeInteger(state.combinedSpent) ||
    state.combinedSpent < 0 ||
    state.combinedSpent + 6_000_000 > state.cap
  )
    throw Error("Shared lifetime budget cannot reserve another request");
}

export async function main() {
  throw Error(
    "Legacy Muse coding launcher is retired. Use native Codex Sol/Terra or Claude Code with explicit Sonnet selection for coding; MetaMuse is reserved for authorized app runtime tests.",
  );
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main().catch((e) => {
    console.error(e.message);
    process.exitCode = 1;
  });
}
