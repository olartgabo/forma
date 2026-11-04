// Replays actual API responses exported by active-measurement-fixture.py in a
// local intercepted browser. SYNTHETIC inputs; no provider and no physical pass.
// Covers question → confirmed inventory record (lost response, reload, same-key
// retry) → explicit recalculation with what changed → "I can't measure this".
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
const { before, after, first, change } = fixture;
const base = `/api/projects/${before.id}`;
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);

async function open(page) {
  await page.goto(`${origin.origin}/?project=${before.id}`);
  await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  return page.getByRole("region", {
    name: "The measurement that matters next",
  });
}

try {
  for (const width of [390, 1280]) {
    const page = await (
      await browser.newContext({
        viewport: { width, height: 900 },
        serviceWorkers: "block",
      })
    ).newPage();
    page.setDefaultTimeout(30000);
    const errors = [];
    const unexpected = [];
    const writes = [];
    let saved = false;
    let puts = 0;
    page.on("pageerror", (e) => errors.push(e.message));
    await page.context().route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(`external ${url.origin}`);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const method = request.method();
      if (method === "PUT" && url.pathname === `${base}/inventory`) {
        const body = request.postDataJSON();
        writes.push(["inventory", body]);
        puts += 1;
        assert.equal(body.expected_revision_id, before.revision_id);
        assert.equal(body.user_confirmed, true);
        assert.equal("requirements" in body, false);
        const [sheet, tape] = body.stocks;
        assert.deepEqual(sheet.width_mm, {
          value: 200,
          unit: "mm",
          source: "user_ruler",
          confirmed: true,
        });
        assert.deepEqual(sheet.height_mm, before.stocks[0].height_mm);
        assert.deepEqual(tape, before.stocks[1]);
        // The server saves the answer but the first response is lost.
        saved = true;
        if (puts === 1) return route.abort("connectionreset");
        return route.fulfill({ json: { ...fixture.saved, replayed: true } });
      }
      if (method === "POST") {
        const body = request.postDataJSON();
        writes.push([url.pathname.split("/").pop(), body]);
        if (url.pathname === `${base}/measurement-decisions`) {
          assert.equal(body.expected_inventory_revision_id, before.revision_id);
          return route.fulfill({ json: first });
        }
        if (url.pathname === `${base}/measurement-decisions/recalculate`) {
          assert.equal(body.expected_inventory_revision_id, after.revision_id);
          assert.equal(body.baseline.decision_id, first.decision_id);
          return route.fulfill({ json: change });
        }
        if (url.pathname === `${base}/measurement-decisions/unavailable`) {
          assert.equal(body.question_id, change.after.question.question_id);
          assert.equal(body.target_key, change.after.question.target.key);
          assert.equal(body.user_confirmed, true);
          return route.fulfill({ json: fixture.unavailable });
        }
        unexpected.push(`POST ${url.pathname}`);
        return route.fulfill({ status: 500, json: { code: "unexpected" } });
      }
      const replay = new Map([
        ["/api/provider/status", { configured: true }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, saved ? after : before],
        [`${base}/media`, { media: [] }],
        [`${base}/designs/readiness`, fixture.readiness],
        [`${base}/plans`, { plans: [] }],
      ]);
      if (replay.has(url.pathname))
        return route.fulfill({ json: replay.get(url.pathname) });
      return route.fulfill({
        status: 503,
        json: { code: "unavailable", message: "Not part of this fixture" },
      });
    });
    let panel = await open(page);
    await panel
      .getByRole("button", { name: "Find the measurement that matters" })
      .click();
    const card = panel.getByRole("article", { name: "Measurement decision" });
    await card.waitFor();
    const text = await card.innerText();
    assert.match(text, /Measure this next/);
    assert.match(text, /Width of sheet synthetic-sheet/);
    assert.match(text, /At least 78 mm/);
    assert.match(text, /Why it matters:/);
    const save = card.getByRole("button", { name: "Save measurement" });
    assert.equal(await save.isDisabled(), true);
    await card.getByLabel("Measured value (mm)").fill("200");
    assert.equal(await save.isDisabled(), true, "needs explicit confirmation");
    await card
      .getByLabel("I measured this myself; it is not a photo estimate")
      .check();
    await save.click();
    await panel
      .getByRole("button", { name: "Retry saving the measurement" })
      .waitFor();

    // Reload: the exact request and the comparison point survive.
    await page.reload();
    panel = await open(page);
    await panel
      .getByRole("button", { name: "Retry saving the measurement" })
      .click();
    const recalc = panel.getByRole("button", { name: "Recalculate" });
    await recalc.waitFor();
    const inventory = writes.filter(([kind]) => kind === "inventory");
    assert.equal(inventory.length, 2);
    assert.deepEqual(inventory[0][1], inventory[1][1]);
    await recalc.click();
    const changed = panel.getByRole("article", { name: "What changed" });
    await changed.waitFor();
    const changedText = await changed.innerText();
    assert.match(changedText, /The decision did not change/);
    assert.match(changedText, /width_mm: unknown → 200/);
    const next = panel.getByRole("article", { name: "Measurement decision" });
    assert.match(await next.innerText(), /Height of sheet synthetic-sheet/);

    // The builder cannot take this measurement: it is not asked again.
    await next.getByRole("button", { name: "I can't measure this" }).click();
    await panel.getByText("No design fits the confirmed stock").waitFor();
    assert.deepEqual(
      writes.map(([kind]) => kind),
      [
        "measurement-decisions",
        "inventory",
        "inventory",
        "recalculate",
        "unavailable",
      ],
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    assert.equal(overflow, false, `horizontal overflow at ${width}px`);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px question with compiler threshold, confirmed inventory answer recovered after a lost response and reload with one key, explicit recalculation showing what changed, unavailable answer stops the question; replayed SYNTHETIC responses only`,
    );
    await page.context().close();
  }
} finally {
  await browser.close();
}
