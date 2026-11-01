import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { workerConfig, workerPrompt } from "./worker-policy.mjs";

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
    state.cap !== 90_000_000 ||
    !Number.isSafeInteger(state.combinedSpent) ||
    state.combinedSpent < 0 ||
    state.combinedSpent + 6_000_000 > state.cap
  )
    throw Error("Shared lifetime budget cannot reserve another request");
}

export async function main(args = process.argv.slice(2)) {
  const options = parseArgs(args);
  const workspace = workspaceRoot(options.workspace);
  const taskBytes = fs.readFileSync(options.taskFile);
  if (taskBytes.length > 16000) throw Error("Task file exceeds 16KB");
  const task = JSON.parse(taskBytes.toString("utf8"));
  const prompt = workerPrompt(task);
  const guardHome = path.resolve(
    process.env.META_GUARD_HOME || path.join(os.homedir(), ".meta-budget"),
  );
  const settings = JSON.parse(
    fs.readFileSync(path.join(guardHome, "settings.json"), "utf8"),
  );
  const base = JSON.parse(
    fs.readFileSync(path.join(guardHome, "opencode.json"), "utf8"),
  );
  if (
    base.model !== "meta_guard/muse-wonder-1.0" ||
    base.small_model !== base.model ||
    JSON.stringify(base.enabled_providers) !== JSON.stringify(["meta_guard"]) ||
    base.provider?.meta_guard?.options?.baseURL !== "http://127.0.0.1:18765/v1"
  )
    throw Error(
      "Both generation and compaction must use the existing guarded provider",
    );
  const config = workerConfig(base, workspace, task);
  config.permission.read = {
    "*": "allow",
    "**/.env*": "deny",
    "**/.meta-budget/**": "deny",
    "**/.git/**": "deny",
    "**/*key.dpapi": "deny",
  };
  const stopped = () => fs.existsSync(path.join(guardHome, "STOP"));
  if (
    stopped() ||
    !Number.isFinite(Date.parse(settings.expires)) ||
    Date.now() >= Date.parse(settings.expires)
  )
    throw Error(
      "STOP or expired verification; no provider or guard process started",
    );
  const status = async () => {
    const r = await fetch("http://127.0.0.1:18765/status", {
      headers: { authorization: `Bearer ${settings.localToken}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) throw Error("Guard status unavailable");
    return r.json();
  };
  let guard, child;
  try {
    let state;
    try {
      state = await status();
    } catch {
      guard = spawn(process.execPath, [path.join(guardHome, "guard.mjs")], {
        stdio: "ignore",
        windowsHide: true,
      });
      guard.on("error", () => {});
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 200));
        try {
          state = await status();
          break;
        } catch {
          /* bounded local startup */
        }
      }
      if (!state) throw Error("Guard unavailable; no direct provider fallback");
    }
    checkStatus(state, stopped());
    const env = { ...process.env };
    const inheritedPath = Object.keys(env).find(
      (k) => k.toLowerCase() === "path",
    );
    const toolDirs = [path.dirname(process.execPath)];
    if (env.MUSE_TOOLS_BIN) toolDirs.unshift(path.resolve(env.MUSE_TOOLS_BIN));
    const systemPath = inheritedPath ? env[inheritedPath] : "";
    if (inheritedPath) delete env[inheritedPath];
    env.PATH = [...toolDirs, systemPath].join(path.delimiter);
    for (const name of Object.keys(env)) {
      if (
        name.startsWith("CODEX_") ||
        /TOKEN|SECRET|PASSWORD|API_KEY|AUTH_TOKEN|BASE_URL/i.test(name)
      )
        delete env[name];
    }
    env.META_GUARD_TOKEN = settings.localToken;
    env.OPENCODE_CONFIG = path.join(guardHome, "opencode.json");
    env.OPENCODE_CONFIG_CONTENT = JSON.stringify(config);
    env.UV_OFFLINE = "1";
    console.log(
      `Starting fresh Muse feature session; shared recorded spend $${(state.combinedSpent / 1e6).toFixed(4)} / $90.`,
    );
    const executable =
      process.platform === "win32"
        ? path.join(guardHome, "bin/opencode/opencode.exe")
        : "opencode";
    child = spawn(executable, ["run", prompt], {
      cwd: workspace,
      env,
      stdio: "inherit",
      windowsHide: true,
    });
    const interrupted = () => child.kill();
    process.once("SIGINT", interrupted);
    try {
      const code = await new Promise((resolve, reject) => {
        child.once("error", reject);
        child.once("exit", (code) => resolve(code ?? 1));
      });
      process.exitCode = code;
    } finally {
      process.removeListener("SIGINT", interrupted);
    }
  } finally {
    if (guard) guard.kill();
  }
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
