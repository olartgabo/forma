import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const SECRET_PART =
  /(^|\.)(env|git|meta-budget|ssh|aws|credentials?|secrets?|tokens?|auth|passwords?|api[-_]?keys?)([.-]|$)/i;
const SECRET_NAME =
  /(secret|credential|password|passwd|api[-_]?key|auth[-_]?token|access[-_]?token|private[-_]?key)/i;
const SECRET_SUFFIX = /\.(key|pem|p12|pfx|dpapi|keystore|jks)$/i;

function isSecretPath(rel) {
  return rel.split("/").some((part) => {
    const lower = part.toLowerCase();
    return (
      SECRET_PART.test(lower) ||
      SECRET_NAME.test(lower) ||
      SECRET_SUFFIX.test(lower) ||
      lower.endsWith("key.dpapi") ||
      lower === "node_modules" ||
      lower.startsWith(".env")
    );
  });
}

function normalizeRel(input, label) {
  if (
    typeof input !== "string" ||
    !input ||
    input.includes("\0") ||
    input.includes("\\") ||
    /[:*?[\]{}\s]/.test(input)
  )
    throw Error(`${label} must be an exact repository-relative path: ${input}`);
  const parts = input.split("/");
  if (
    input.startsWith("/") ||
    parts.some(
      (part) =>
        !part ||
        part === "." ||
        part === ".." ||
        part.endsWith(" ") ||
        part.endsWith("."),
    )
  )
    throw Error(`${label} must be an exact repository-relative path: ${input}`);
  return parts.join("/");
}

function validateAllowed(filesAllowed) {
  if (!Array.isArray(filesAllowed))
    throw Error("filesAllowed must be an array of exact paths");
  const allowed = new Set();
  for (const file of filesAllowed) {
    const rel = normalizeRel(file, "Allowed path");
    if (isSecretPath(rel))
      throw Error(`Secret or credential artifact is not allowed: ${rel}`);
    allowed.add(rel);
  }
  return allowed;
}

function git(root, args, options = {}) {
  return execFileSync("git", ["--no-optional-locks", "-C", root, ...args], {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 16 * 1024 * 1024,
    ...options,
  });
}

function assertNoLinkedAlias(rootReal, rel) {
  const parts = rel.split("/");
  let current = rootReal;
  for (let i = 0; i < parts.length; i++) {
    current = path.join(current, parts[i]);
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch (error) {
      if (error && error.code === "ENOENT") {
        // A missing tail (for example a deletion) is safe only if every
        // existing ancestor already matched its literal location.
        return;
      }
      throw Error(`Changed path cannot be inspected safely: ${rel}`);
    }
    if (stat.isSymbolicLink())
      throw Error(`Linked path is not allowed: ${rel}`);
    if (i < parts.length - 1 && !stat.isDirectory())
      throw Error(`Changed path cannot be inspected safely: ${rel}`);
    if (i === parts.length - 1 && stat.isDirectory())
      throw Error(`Changed path is not a regular file: ${rel}`);
  }
  let real;
  try {
    real = fs.realpathSync(path.join(rootReal, ...parts));
  } catch {
    return;
  }
  const expected = path.join(rootReal, ...parts);
  const same =
    process.platform === "win32"
      ? real.toLowerCase() === expected.toLowerCase()
      : real === expected;
  if (!same) throw Error(`Linked path is not allowed: ${rel}`);
}

function decodeUtf8(buffer, rel) {
  if (buffer.includes(0))
    throw Error(`Binary content is not allowed in review packet: ${rel}`);
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    throw Error(`Non-UTF-8 content is not allowed in review packet: ${rel}`);
  }
}

function parseStatus(buffer) {
  const tokens = buffer.toString("utf8").split("\0");
  const entries = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (!token) continue;
    if (token.length < 4 || token[2] !== " ")
      throw Error("Unexpected git status output");
    const indexStatus = token[0];
    const worktreeStatus = token[1];
    const rel = token.slice(3);
    let previousPath = null;
    if (
      indexStatus === "R" ||
      indexStatus === "C" ||
      worktreeStatus === "R" ||
      worktreeStatus === "C"
    ) {
      previousPath = tokens[++i] ?? null;
      if (!previousPath) throw Error("Unexpected git status rename output");
    }
    entries.push({ indexStatus, worktreeStatus, path: rel, previousPath });
  }
  return entries;
}

function statusFor(entry, beforeExists, afterExists) {
  if (entry.indexStatus === "?" && entry.worktreeStatus === "?")
    return "untracked";
  if (entry.previousPath) return "renamed";
  if (!afterExists && beforeExists) return "deleted";
  if (!beforeExists && afterExists)
    return entry.indexStatus === "A" ? "added" : "untracked";
  return "modified";
}

export function buildReviewPacket(root, filesAllowed, maxBytes = 240000) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 0)
    throw Error("maxBytes must be a non-negative safe integer");
  const allowed = validateAllowed(filesAllowed);

  let rootReal;
  try {
    rootReal = fs.realpathSync(root);
  } catch {
    throw Error("Review root must be an existing repository root");
  }
  if (!fs.statSync(rootReal).isDirectory())
    throw Error("Review root must be an existing repository root");

  let top;
  try {
    top = git(rootReal, ["rev-parse", "--show-toplevel"], {
      encoding: "utf8",
    }).trim();
  } catch {
    throw Error("Review root must be an existing repository root");
  }
  const topReal = fs.realpathSync(top);
  const sameRoot =
    process.platform === "win32"
      ? topReal.toLowerCase() === rootReal.toLowerCase()
      : topReal === rootReal;
  if (!sameRoot) throw Error("Review root must be the exact repository root");

  const statusBuffer = git(rootReal, [
    "status",
    "--porcelain",
    "-z",
    "--untracked-files=all",
  ]);
  const entries = parseStatus(statusBuffer);

  // Validate every changed path, including rename sources, before reading
  // any working-tree contents or HEAD blobs.
  for (const entry of entries) {
    for (const candidate of [entry.path, entry.previousPath]) {
      if (candidate === null) continue;
      const rel = normalizeRel(candidate, "Changed path");
      if (rel !== candidate)
        throw Error(`Changed path is not normalized: ${candidate}`);
      if (!allowed.has(rel))
        throw Error(
          `Changed path is out of scope (not in filesAllowed): ${rel}`,
        );
      if (isSecretPath(rel))
        throw Error(
          `Secret or credential artifact rejected before reading contents: ${rel}`,
        );
    }
  }
  for (const entry of entries) {
    assertNoLinkedAlias(rootReal, entry.path);
    if (entry.previousPath) assertNoLinkedAlias(rootReal, entry.previousPath);
  }

  let hasHead = true;
  try {
    git(rootReal, ["rev-parse", "--verify", "-q", "HEAD"], {
      encoding: "utf8",
    });
  } catch {
    hasHead = false;
  }

  // Collect sizes before reading contents so oversized input is rejected
  // explicitly instead of being truncated.
  const plans = entries.map((entry) => {
    const sourcePath = entry.previousPath ?? entry.path;
    let beforeSize = 0;
    let beforeExists = false;
    if (hasHead) {
      try {
        const sizeText = git(
          rootReal,
          ["cat-file", "-s", `HEAD:${sourcePath}`],
          { encoding: "utf8" },
        ).trim();
        if (!/^\d+$/.test(sizeText)) throw Error("bad size");
        beforeSize = Number(sizeText);
        beforeExists = true;
      } catch {
        beforeExists = false;
        beforeSize = 0;
      }
    }
    const absolute = path.join(rootReal, ...entry.path.split("/"));
    let afterExists = false;
    let afterSize = 0;
    try {
      const stat = fs.lstatSync(absolute);
      if (stat.isFile()) {
        afterExists = true;
        afterSize = stat.size;
      } else if (!stat.isSymbolicLink()) {
        throw Error(`Changed path is not a regular file: ${entry.path}`);
      }
    } catch (error) {
      if (!error || error.code !== "ENOENT") throw error;
    }
    return {
      entry,
      sourcePath,
      beforeExists,
      beforeSize,
      afterExists,
      afterSize,
    };
  });

  let totalBytes = 0;
  for (const plan of plans) {
    for (const [size, rel] of [
      [plan.beforeSize, plan.sourcePath],
      [plan.afterSize, plan.entry.path],
    ]) {
      if (size > maxBytes)
        throw Error(
          `Content for ${rel} (${size} bytes) exceeds maxBytes (${maxBytes} bytes); refusing to truncate`,
        );
      totalBytes += size;
      if (totalBytes > maxBytes)
        throw Error(
          `Aggregate review packet content (${totalBytes} bytes) exceeds maxBytes (${maxBytes} bytes); refusing to truncate`,
        );
    }
  }

  const changes = plans
    .map((plan) => {
      const before = plan.beforeExists
        ? decodeUtf8(
            git(rootReal, ["show", `HEAD:${plan.sourcePath}`]),
            plan.sourcePath,
          )
        : null;
      const after = plan.afterExists
        ? decodeUtf8(
            fs.readFileSync(path.join(rootReal, ...plan.entry.path.split("/"))),
            plan.entry.path,
          )
        : null;
      return {
        path: plan.entry.path,
        previousPath: plan.entry.previousPath,
        status: statusFor(plan.entry, plan.beforeExists, plan.afterExists),
        indexStatus: plan.entry.indexStatus,
        worktreeStatus: plan.entry.worktreeStatus,
        before,
        after,
        beforeBytes: plan.beforeExists ? plan.beforeSize : 0,
        afterBytes: plan.afterExists ? plan.afterSize : 0,
      };
    })
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));

  const packet = {
    version: 1,
    root: rootReal,
    filesAllowed: [...allowed],
    maxBytes,
    totalBytes,
    changes,
  };
  // Prove the packet is JSON serializable without retaining a string copy.
  JSON.stringify(packet);
  return packet;
}
