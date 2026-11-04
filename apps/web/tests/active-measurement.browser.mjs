// Replays actual API responses exported by active-measurement-fixture.py in a
// local intercepted browser. SYNTHETIC inputs; no provider and no physical pass.
// Design flow: question → "I can't measure this" moves to another sheet with an
// empty answer → confirmed inventory record (lost response, reload, same-key
// retry) → recalculation reaches the next question with the settings carried
// by the server (only the first revision was configured) → a refused save is
// never shown as saved. Built-stand flow: the stand question is kept as the comparison point
// across a reload, values are recorded in the #146 form, and recalculation
// shows the change.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node active-measurement.browser.mjs <playwright> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("Only a local intercepted browser is permitted");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const ruler = (value) => ({
  value,
  unit: "mm",
  source: "user_ruler",
  confirmed: true,
});

async function open(page, projectId) {
  await page.goto(`${origin.origin}/?project=${projectId}`);
  await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  return page.getByRole("region", {
    name: "The measurement that matters next",
  });
}

async function newPage(width, handle) {
  const page = await (
    await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    })
  ).newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  const unexpected = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.context().route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) {
      unexpected.push(`external ${url.origin}`);
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    // A handler returns the route promise when it answered the request.
    const handled = handle(route, request, url);
    if (handled) return handled;
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.fulfill({ status: 500, json: { code: "unexpected" } });
    }
    return route.fulfill({
      status: 503,
      json: { code: "unavailable", message: "Not part of this fixture" },
    });
  });
  return { page, errors, unexpected };
}

async function finish({ page, errors, unexpected }, width) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  assert.equal(overflow, false, `horizontal overflow at ${width}px`);
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpected, []);
  await page.context().close();
}

async function designFlow(width) {
  const { before, after, first, declined, change } = fixture;
  const base = `/api/projects/${before.id}`;
  const writes = [];
  let saved = false;
  let puts = 0;
  const session = await newPage(width, (route, request, url) => {
    const method = request.method();
    const common = new Map([
      ["/api/provider/status", { configured: true }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, saved ? after : before],
      [`${base}/media`, { media: [] }],
      [`${base}/designs/readiness`, fixture.readiness],
      [`${base}/plans`, { plans: [] }],
    ]);
    if (method === "GET" && common.has(url.pathname))
      return route.fulfill({ json: common.get(url.pathname) });
    if (method === "PUT" && url.pathname === `${base}/inventory`) {
      const body = request.postDataJSON();
      writes.push(["inventory", body]);
      puts += 1;
      assert.equal(body.user_confirmed, true);
      assert.equal("requirements" in body, false);
      const [a, b, tape] = body.stocks;
      if (puts <= 2) {
        assert.equal(body.expected_revision_id, before.revision_id);
        // Sheet A, which the builder could not measure, is untouched.
        assert.deepEqual(a, before.stocks[0]);
        assert.deepEqual(b.width_mm, ruler(200));
        assert.deepEqual(tape, before.stocks[2]);
        saved = true;
        // The server saves the answer but the first response is lost.
        if (puts === 1) return route.abort("connectionreset");
        return route.fulfill({ json: { ...fixture.saved, replayed: true } });
      }
      // A definite refusal: nothing is saved.
      assert.equal(body.expected_revision_id, after.revision_id);
      assert.deepEqual(b.height_mm, ruler(300));
      return route.fulfill({ status: 409, json: fixture.refused });
    }
    if (method !== "POST") return undefined;
    const body = request.postDataJSON();
    writes.push([url.pathname.split("/").pop(), body]);
    if (url.pathname === `${base}/measurement-decisions`) {
      assert.equal(body.expected_inventory_revision_id, before.revision_id);
      return route.fulfill({ json: first });
    }
    if (url.pathname === `${base}/measurement-decisions/unavailable`) {
      assert.equal(body.question_id, first.question.question_id);
      assert.equal(body.target_key, first.question.target.key);
      assert.equal(body.user_confirmed, true);
      return route.fulfill({ json: declined });
    }
    if (url.pathname === `${base}/measurement-decisions/recalculate`) {
      assert.equal(body.expected_inventory_revision_id, after.revision_id);
      assert.equal(body.baseline.decision_id, declined.decision_id);
      return route.fulfill({ json: change });
    }
    return undefined;
  });
  const { page } = session;
  let panel = await open(page, before.id);
  await panel
    .getByRole("button", { name: "Find the measurement that matters" })
    .click();
  let card = panel.getByRole("article", { name: "Measurement decision" });
  await card.waitFor();
  let text = await card.innerText();
  assert.match(text, /Measure this next/);
  assert.match(text, /Width of sheet synthetic-sheet\n/);
  assert.match(text, /At least 78 mm/);
  assert.match(text, /Why it matters:/);
  const value = () => card.getByLabel("Measured value (mm)");
  const confirm = () =>
    card.getByLabel("I measured this myself; it is not a photo estimate");
  const save = () => card.getByRole("button", { name: "Save measurement" });
  assert.equal(await save().isDisabled(), true);
  await value().fill("200");
  assert.equal(await save().isDisabled(), true, "needs explicit confirmation");
  await confirm().check();
  assert.equal(await save().isDisabled(), false);

  // Sheet A cannot be measured. Sheet B's question starts empty: the value
  // and confirmation typed for sheet A never carry over.
  await card.getByRole("button", { name: "I can't measure this" }).click();
  await card.getByText("Width of sheet synthetic-sheet-b").waitFor();
  assert.equal(await value().inputValue(), "");
  assert.equal(await confirm().isChecked(), false);
  assert.equal(await save().isDisabled(), true);

  await value().fill("200");
  await confirm().check();
  await save().click();
  await panel
    .getByRole("button", { name: "Retry saving the measurement" })
    .waitFor();

  // Reload: the exact request and the comparison point survive.
  await page.reload();
  panel = await open(page, before.id);
  await panel
    .getByRole("button", { name: "Retry saving the measurement" })
    .click();
  await panel.getByText("A measurement was saved.").waitFor();
  const inventory = writes.filter(([kind]) => kind === "inventory");
  assert.equal(inventory.length, 2);
  assert.deepEqual(inventory[0][1], inventory[1][1]);
  await panel.getByRole("button", { name: "Recalculate" }).click();
  const changed = panel.getByRole("article", { name: "What changed" });
  await changed.waitFor();
  const changedText = await changed.innerText();
  assert.match(changedText, /synthetic-sheet-b:width_mm: unknown → 200/);
  assert.match(changedText, /The next measurement is now: Height of sheet/);
  card = panel.getByRole("article", { name: "Measurement decision" });
  text = await card.innerText();
  // The settings reviewed for the first revision followed the measured sheet.
  assert.match(text, /Height of sheet synthetic-sheet-b/);
  assert.match(text, /Design settings/);
  assert.match(
    text,
    new RegExp(
      `settings reviewed for inventory revision ${before.revision_id}`,
    ),
  );
  assert.equal(await value().inputValue(), "");
  assert.equal(await confirm().isChecked(), false);
  await value().fill("300");
  await confirm().check();
  await save().click();
  await panel.getByText(/The measurement was not saved\./).waitFor();
  assert.equal(await panel.getByText("A measurement was saved.").count(), 0);
  assert.equal(
    await panel.getByRole("button", { name: "Recalculate" }).count(),
    0,
  );
  assert.equal(
    await panel
      .getByRole("button", { name: "Retry saving the measurement" })
      .count(),
    0,
  );
  assert.deepEqual(
    writes.map(([kind]) => kind),
    [
      "measurement-decisions",
      "unavailable",
      "inventory",
      "inventory",
      "recalculate",
      "inventory",
    ],
  );
  await finish(session, width);
}

async function standFlow(width) {
  const { project, question, change, plans } = fixture.stand;
  const base = `/api/projects/${project.id}`;
  const writes = [];
  const session = await newPage(width, (route, request, url) => {
    const method = request.method();
    const common = new Map([
      ["/api/provider/status", { configured: true }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, project],
      [`${base}/media`, { media: [] }],
      [`${base}/plans`, plans],
    ]);
    if (method === "GET" && common.has(url.pathname))
      return route.fulfill({ json: common.get(url.pathname) });
    if (method !== "POST") return undefined;
    const body = request.postDataJSON();
    writes.push(url.pathname.split("/").pop());
    assert.equal(body.expected_active_version_id, project.active_version_id);
    if (url.pathname === `${base}/measurement-decisions`)
      return route.fulfill({ json: question });
    if (url.pathname === `${base}/measurement-decisions/recalculate`) {
      assert.equal(body.baseline.decision_id, question.decision_id);
      return route.fulfill({ json: change });
    }
    return undefined;
  });
  const { page } = session;
  let panel = await open(page, project.id);
  await panel
    .getByRole("button", { name: "Find the measurement that matters" })
    .click();
  const card = panel.getByRole("article", { name: "Measurement decision" });
  await card.waitFor();
  const text = await card.innerText();
  assert.match(text, /Assembled stand and device/);
  assert.match(text, /Record assembled-stand measurements/);
  assert.equal(
    await card.getByRole("button", { name: "Save measurement" }).count(),
    0,
  );
  const notice = /After you record the assembled-stand measurements/;
  await panel.getByText(notice).waitFor();
  assert.equal(await panel.getByText("A measurement was saved.").count(), 0);

  // The values are recorded in the #146 form; the comparison point survives.
  await page.reload();
  panel = await open(page, project.id);
  await panel.getByText(notice).waitFor();
  await panel.getByRole("button", { name: "Recalculate" }).click();
  const changed = panel.getByRole("article", { name: "What changed" });
  await changed.waitFor();
  const changedText = await changed.innerText();
  assert.match(changedText, /The decision changed/);
  assert.match(changedText, /assembled-stand measurement records: 0 → 1/);
  assert.match(
    await panel
      .getByRole("article", { name: "Measurement decision" })
      .innerText(),
    /No further measurement is needed/,
  );
  assert.deepEqual(writes, ["measurement-decisions", "recalculate"]);
  await finish(session, width);
}

async function storageFailureAfterSave(width, failureKind) {
  const { before, after, declined } = fixture;
  const base = `/api/projects/${before.id}`;
  const writes = [];
  let saved = false;
  let refreshedAfterSave = false;
  const session = await newPage(width, (route, request, url) => {
    if (request.method() === "GET") {
      if (url.pathname === base && saved) refreshedAfterSave = true;
      const common = new Map([
        ["/api/provider/status", { configured: true }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, saved ? after : before],
        [`${base}/media`, { media: [] }],
        [`${base}/designs/readiness`, fixture.readiness],
        [`${base}/plans`, { plans: [] }],
      ]);
      if (common.has(url.pathname))
        return route.fulfill({ json: common.get(url.pathname) });
    }
    if (
      request.method() === "POST" &&
      url.pathname === `${base}/measurement-decisions`
    )
      return route.fulfill({ json: declined });
    if (
      request.method() === "POST" &&
      url.pathname === `${base}/measurement-decisions/recalculate`
    ) {
      assert.equal(
        request.postDataJSON().baseline.decision_id,
        declined.decision_id,
      );
      return route.fulfill({ json: fixture.change });
    }
    if (request.method() === "PUT" && url.pathname === `${base}/inventory`) {
      writes.push(request.postDataJSON());
      saved = true;
      return route.fulfill({
        json: { ...fixture.saved, replayed: writes.length > 1 },
      });
    }
    return undefined;
  });
  const { page } = session;
  // Arm storage failure only after fetch receives the successful inventory
  // response. The exact receipt must already have been retained and dispatched.
  await page.addInitScript((kind) => {
    const originalFetch = window.fetch;
    const original = Storage.prototype[kind];
    let armed = false;
    window.storageFailures = 0;
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (
        response.ok &&
        String(args[0]).endsWith("/inventory") &&
        args[1]?.method === "PUT"
      )
        armed = true;
      return response;
    };
    Storage.prototype[kind] = function (key, ...args) {
      const target =
        kind === "removeItem"
          ? "forma-measurement-answer-pending-v1:"
          : "forma-measurement-baseline-v2:";
      if (armed && !window.disableStorageFailure && key.startsWith(target)) {
        window.storageFailures += 1;
        throw new Error("Injected post-save storage failure");
      }
      return original.call(this, key, ...args);
    };
  }, failureKind);
  let panel = await open(page, before.id);
  await panel
    .getByRole("button", { name: "Find the measurement that matters" })
    .click();
  await panel.getByLabel("Measured value (mm)").fill("200");
  await panel
    .getByLabel("I measured this myself; it is not a photo estimate")
    .check();
  const refreshed = page.waitForResponse(
    (response) =>
      response.url().endsWith(base) && response.request().method() === "GET",
  );
  await panel.getByRole("button", { name: "Save measurement" }).click();
  await panel
    .getByText(
      "The measurement was saved, but its local recovery record still needs updating.",
      { exact: false },
    )
    .waitFor();
  await page.waitForFunction(() => window.storageFailures > 0);
  await refreshed;
  assert.equal(
    refreshedAfterSave,
    true,
    "onSaved refreshes the project after storage failure",
  );
  assert.equal(
    await panel.getByText(/The measurement was not saved/).count(),
    0,
  );
  assert.equal(await panel.getByText(/its result is unknown/).count(), 0);
  const retained = await page.evaluate(
    () =>
      Object.entries(localStorage).find(([key]) =>
        key.startsWith("forma-measurement-answer-pending-v1:"),
      )?.[1],
  );
  assert.deepEqual(JSON.parse(retained).body, writes[0]);
  // A fresh page loses in-memory success, but retries the identical receipt.
  await page.reload();
  await page.evaluate(() => {
    window.disableStorageFailure = true;
  });
  panel = await open(page, before.id);
  await page.evaluate(() => {
    window.disableStorageFailure = true;
  });
  const replayed = page.waitForResponse((response) =>
    response.url().endsWith(`${base}/inventory`),
  );
  await panel
    .getByRole("button", { name: "Retry saving the measurement" })
    .click();
  await replayed;
  assert.equal(writes.length, 2);
  assert.deepEqual(writes[1], writes[0]);
  await panel.getByText("A measurement was saved.").waitFor();
  await panel.getByRole("button", { name: "Recalculate" }).click();
  await panel.getByRole("article", { name: "What changed" }).waitFor();
  await finish(session, width);
}

try {
  for (const width of [390, 1280]) {
    for (const failureKind of ["removeItem", "setItem"]) {
      await storageFailureAfterSave(width, failureKind);
      console.log(
        `PASS ${width}px ${failureKind} failure after successful save: saved state, project refresh and exact receipt retry preserved`,
      );
    }
    await designFlow(width);
    console.log(
      `PASS ${width}px design: declining one sheet leaves the next sheet's answer empty, confirmed inventory answer recovered after a lost response and reload with one key, recalculation reaches the next question with server-carried settings (no operator step for the new revision), a refused save is not shown as saved; replayed SYNTHETIC responses only`,
    );
    await standFlow(width);
    console.log(
      `PASS ${width}px built stand: question kept as the comparison point across a reload, recalculation after #146 values shows the change; replayed SYNTHETIC responses only`,
    );
  }
} finally {
  await browser.close();
}
