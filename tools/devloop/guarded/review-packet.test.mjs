import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { buildReviewPacket } from "./review-packet.mjs";

function git(root, ...args) {
  return execFileSync("git", ["-C", root, ...args], {
    encoding: "utf8",
    windowsHide: true,
  });
}

function makeRepo(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "review-packet-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  git(root, "init", "-q");
  git(root, "config", "user.name", "Review Packet Test");
  git(root, "config", "user.email", "review-packet@example.invalid");
  git(root, "config", "core.autocrlf", "false");
  return root;
}

function write(root, rel, content) {
  const target = path.join(root, ...rel.split("/"));
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
}

function commitAll(root, message = "initial") {
  git(root, "add", "-A");
  git(root, "commit", "-q", "-m", message);
}

function byPath(packet) {
  return new Map(packet.changes.map((change) => [change.path, change]));
}

test("clean repository returns explicit empty changes", (t) => {
  const root = makeRepo(t);
  write(root, "a.txt", "hello\n");
  commitAll(root);
  const packet = buildReviewPacket(root, ["a.txt"]);
  assert.deepEqual(packet.changes, []);
  assert.equal(packet.totalBytes, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(packet)), packet);
});

test("tracked unstaged, staged, staged-new, untracked and deleted changes carry complete before/after", (t) => {
  const root = makeRepo(t);
  write(root, "unstaged.txt", "before-unstaged\n");
  write(root, "staged.txt", "before-staged\n");
  write(root, "deleted.txt", "before-deleted\n");
  write(root, "both.txt", "before-both\n");
  commitAll(root);

  write(root, "unstaged.txt", "after-unstaged\n");
  write(root, "staged.txt", "after-staged\n");
  git(root, "add", "staged.txt");
  write(root, "both.txt", "staged-both\n");
  git(root, "add", "both.txt");
  write(root, "both.txt", "after-both\n");
  fs.rmSync(path.join(root, "deleted.txt"));
  write(root, "staged-new.txt", "staged-new\n");
  git(root, "add", "staged-new.txt");
  write(root, "untracked.txt", "untracked\n");

  const allowed = [
    "unstaged.txt",
    "staged.txt",
    "deleted.txt",
    "both.txt",
    "staged-new.txt",
    "untracked.txt",
  ];
  const headBefore = git(root, "rev-parse", "HEAD").trim();
  const indexBefore = crypto
    .createHash("sha256")
    .update(fs.readFileSync(path.join(root, ".git", "index")))
    .digest("hex");
  const statusBefore = git(
    root,
    "status",
    "--porcelain",
    "-z",
    "--untracked-files=all",
  );

  const packet = buildReviewPacket(root, allowed);
  const changes = byPath(packet);
  assert.deepEqual([...changes.keys()].sort(), [...allowed].sort());

  assert.equal(changes.get("unstaged.txt").status, "modified");
  assert.equal(changes.get("unstaged.txt").before, "before-unstaged\n");
  assert.equal(changes.get("unstaged.txt").after, "after-unstaged\n");

  assert.equal(changes.get("staged.txt").status, "modified");
  assert.equal(changes.get("staged.txt").before, "before-staged\n");
  assert.equal(changes.get("staged.txt").after, "after-staged\n");
  assert.equal(changes.get("staged.txt").indexStatus, "M");

  assert.equal(changes.get("both.txt").before, "before-both\n");
  assert.equal(changes.get("both.txt").after, "after-both\n");
  assert.equal(changes.get("both.txt").indexStatus, "M");
  assert.equal(changes.get("both.txt").worktreeStatus, "M");

  assert.equal(changes.get("deleted.txt").status, "deleted");
  assert.equal(changes.get("deleted.txt").before, "before-deleted\n");
  assert.equal(changes.get("deleted.txt").after, null);

  assert.equal(changes.get("staged-new.txt").status, "added");
  assert.equal(changes.get("staged-new.txt").before, null);
  assert.equal(changes.get("staged-new.txt").after, "staged-new\n");

  assert.equal(changes.get("untracked.txt").status, "untracked");
  assert.equal(changes.get("untracked.txt").before, null);
  assert.equal(changes.get("untracked.txt").after, "untracked\n");

  assert.equal(
    packet.totalBytes,
    packet.changes.reduce(
      (sum, change) => sum + change.beforeBytes + change.afterBytes,
      0,
    ),
  );
  assert.deepEqual(JSON.parse(JSON.stringify(packet)), packet);

  // Building a packet must not mutate HEAD, the index or working content.
  assert.equal(git(root, "rev-parse", "HEAD").trim(), headBefore);
  assert.equal(
    crypto
      .createHash("sha256")
      .update(fs.readFileSync(path.join(root, ".git", "index")))
      .digest("hex"),
    indexBefore,
  );
  assert.equal(
    git(root, "status", "--porcelain", "-z", "--untracked-files=all"),
    statusBefore,
  );
  assert.equal(
    fs.readFileSync(path.join(root, "both.txt"), "utf8"),
    "after-both\n",
  );
});

test("staged deletion reports before content and null after", (t) => {
  const root = makeRepo(t);
  write(root, "gone.txt", "gone-before\n");
  commitAll(root);
  git(root, "rm", "-q", "gone.txt");
  const packet = buildReviewPacket(root, ["gone.txt"]);
  assert.equal(packet.changes.length, 1);
  assert.equal(packet.changes[0].status, "deleted");
  assert.equal(packet.changes[0].before, "gone-before\n");
  assert.equal(packet.changes[0].after, null);
});

test("out-of-allowlist synthetic secret is rejected before its contents are read", (t) => {
  const root = makeRepo(t);
  write(root, "a.txt", "hello\n");
  commitAll(root);
  // Non-UTF8 content: if contents were read first, the error would be
  // about binary/non-UTF8 content instead of scope.
  fs.writeFileSync(
    path.join(root, "synthetic-secret.txt"),
    Buffer.from([0xff, 0xfe, 0x00, 0x41]),
  );
  write(root, "a.txt", "changed\n");
  assert.throws(
    () => buildReviewPacket(root, ["a.txt"]),
    /out of scope|not in filesAllowed/i,
  );
});

test("allowlisted secret artifact is rejected", (t) => {
  const root = makeRepo(t);
  write(root, "a.txt", "hello\n");
  commitAll(root);
  write(root, "credentials.txt", "synthetic-not-a-real-credential\n");
  assert.throws(
    () => buildReviewPacket(root, ["a.txt", "credentials.txt"]),
    /secret|credential/i,
  );
});

test("directory junction escape is rejected before reading outside contents", (t) => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "review-packet-link-"));
  t.after(() => fs.rmSync(fixture, { recursive: true, force: true }));
  const root = path.join(fixture, "repo");
  const outside = path.join(fixture, "outside");
  fs.mkdirSync(root);
  fs.mkdirSync(outside);
  git(root, "init", "-q");
  git(root, "config", "user.name", "Review Packet Test");
  git(root, "config", "user.email", "review-packet@example.invalid");
  write(root, "a.txt", "hello\n");
  commitAll(root);
  fs.writeFileSync(path.join(outside, "escaped.txt"), "outside\n");
  fs.symlinkSync(
    outside,
    path.join(root, "linked"),
    process.platform === "win32" ? "junction" : "dir",
  );
  // Stage the link parent entry: adding the child through a Linux symlink
  // fails in git ("pathspec is beyond a symbolic link") before the packet
  // builder runs. Linux records the symlink itself as "linked"; Windows
  // traverses the junction and records "linked/escaped.txt". Allow both so
  // either entry reaches the linked-path rejection in buildReviewPacket.
  git(root, "add", "-f", "linked");
  assert.throws(
    () => buildReviewPacket(root, ["linked", "linked/escaped.txt"]),
    /linked|escapes|not allowed/i,
  );
});

test("binary and non-UTF8 working contents are rejected, never truncated", (t) => {
  const root = makeRepo(t);
  write(root, "a.txt", "hello\n");
  commitAll(root);
  fs.writeFileSync(path.join(root, "a.txt"), Buffer.from([0x41, 0x00, 0xff]));
  assert.throws(() => buildReviewPacket(root, ["a.txt"]), /binary|UTF-8/i);
  fs.writeFileSync(path.join(root, "a.txt"), Buffer.from([0xc3, 0x28]));
  assert.throws(() => buildReviewPacket(root, ["a.txt"]), /binary|UTF-8/i);
});

test("individual and aggregate overflow are rejected explicitly", (t) => {
  const root = makeRepo(t);
  write(root, "a.txt", "1234567890\n");
  write(root, "b.txt", "1234567890\n");
  commitAll(root);
  write(root, "a.txt", "a".repeat(30));
  write(root, "b.txt", "b".repeat(30));
  // Each file (plus its before image) fits a loose reading, together they do not.
  assert.throws(
    () => buildReviewPacket(root, ["a.txt", "b.txt"], 50),
    /exceeds maxBytes|refusing to truncate/i,
  );
  assert.throws(
    () => buildReviewPacket(root, ["a.txt", "b.txt"], 10),
    /exceeds maxBytes|refusing to truncate/i,
  );
});

test("no test file needs to be in the allowlist", (t) => {
  const root = makeRepo(t);
  write(root, "src/feature.txt", "one\n");
  commitAll(root);
  write(root, "src/feature.txt", "two\n");
  const packet = buildReviewPacket(root, ["src/feature.txt"]);
  assert.equal(packet.changes[0].after, "two\n");
});
