import path from "node:path";
import fs from "node:fs";

export const CHECKS = Object.freeze([
  "uv run --locked --offline pytest -q",
  "uv run --locked --offline ruff check .",
  "uv run --locked --offline ruff format --check .",
  "npm run contracts:check",
  "node --test tools/devloop/guarded/*.test.mjs",
  "npm run format:check",
]);

export const WORKER_ROLE = `You are the Muse implementation worker. Own the coding,
regression tests, execution of offline checks, and repairs for this single feature.
Follow the supplied acceptance criteria and exact edit allowlist. Do not weaken
tests to make failures disappear. Run the permitted checks yourself, report actual
commands and exit codes, and repair failures without requesting premium review.
After TWO unsuccessful repair attempts, stop with STUCK, the smallest reproducible
failure, files changed, checks run, and a concrete question for the planner. Never
loop indefinitely. If green, return READY_FOR_FINAL_REVIEW with a concise summary.
Do not publish, commit, call providers directly, change billing or guard settings,
install dependencies, or delegate to other models. Missing prerequisites are blockers.
Keep only the current task, decisions, relevant files and latest failure in context.
Automatic compaction preserves acceptance criteria, edit scope, completed work,
repair count and blockers; it must not reset repair or spending limits.`;

export function validateTask(task) {
  if (
    !task ||
    typeof task.goal !== "string" ||
    !task.goal.trim() ||
    !Array.isArray(task.acceptance_criteria) ||
    !task.acceptance_criteria.length ||
    task.acceptance_criteria.some((x) => typeof x !== "string" || !x.trim()) ||
    !Array.isArray(task.files_allowed) ||
    !task.files_allowed.length ||
    task.files_allowed.length > 12
  )
    throw Error(
      "Task requires goal, acceptance_criteria and at most 12 exact source/test paths",
    );
  for (const file of task.files_allowed) {
    if (
      typeof file !== "string" ||
      !/^(packages\/(domain|compiler|replanner|renderer)\/(src|tests)\/|apps\/api\/(src\/forma_api|tests)\/|tools\/devloop\/)/.test(
        file,
      ) ||
      /[\\:*?\[\]{}\s]/.test(file) ||
      file.split("/").some((x) => !x || x === "." || x === "..") ||
      /(^|\/)(\.env[^/]*|\.git|\.meta-budget|node_modules|__pycache__|[^/]*\.lock|[^/]*secret[^/]*|[^/]*key\.dpapi)($|\/)/i.test(
        file,
      )
    )
      throw Error("Task edit path must be an exact lane source/test file");
  }
  if (
    !task.files_allowed.some(
      (x) =>
        /(^|\/)(tests\/|test_[^/]+\.py$)/.test(x) || /\.test\.mjs$/.test(x),
    )
  )
    throw Error("Muse must own at least one regression test file");
  return task;
}

export function workerConfig(base, workspace, task) {
  validateTask(task);
  const canonical = fs.realpathSync(workspace);
  for (const file of task.files_allowed) {
    let ancestor = path.join(workspace, file);
    while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
    const relative = path.relative(canonical, fs.realpathSync(ancestor));
    if (relative.startsWith("..") || path.isAbsolute(relative))
      throw Error("Task path escapes the workspace through a link");
  }
  const config = structuredClone(base);
  config.compaction = { auto: true, prune: true, reserved: 10000 };
  config.permission = {
    ...config.permission,
    edit: { "*": "deny" },
    bash: { "*": "deny" },
    external_directory: "deny",
    task: "deny",
    webfetch: "deny",
    websearch: "deny",
  };
  for (const file of task.files_allowed) {
    config.permission.edit[file] = "allow";
    config.permission.edit[path.join(workspace, file).replaceAll("\\", "/")] =
      "allow";
    config.permission.edit[path.join(workspace, file)] = "allow";
  }
  for (const command of CHECKS) config.permission.bash[command] = "allow";
  return config;
}

export function workerPrompt(task, instruction = "") {
  validateTask(task);
  const prompt = `${WORKER_ROLE}\nAllowed offline checks:\n${CHECKS.join("\n")}\nTask packet:\n${JSON.stringify(task)}\n${instruction}`;
  if (Buffer.byteLength(prompt, "utf8") > 16000)
    throw Error(
      "Task packet exceeds 16KB; use relevant file references instead of chat history",
    );
  return prompt;
}
