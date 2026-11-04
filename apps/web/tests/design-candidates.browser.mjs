// Replays actual API responses exported by design-candidates-fixture.py in a
// local intercepted browser. SYNTHETIC inputs; no provider and no physical pass.
// Covers search → comparison → probe → explicit selection (with a lost response
// and same-key retry) → the existing, separate plan approval.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node design-candidates.browser.mjs <playwright> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("Only a local intercepted browser is permitted");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { project, search, probe, select, version } = fixture;
const base = `/api/projects/${project.id}`;
const [first, second] = search.candidates;
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
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
    const posts = [];
    let saved = false;
    let selectCalls = 0;
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
      if (method === "POST") {
        const body = request.postDataJSON();
        posts.push([url.pathname, body]);
        if (url.pathname === `${base}/synthesis/search`) {
          assert.equal(
            body.expected_inventory_revision_id,
            project.revision_id,
          );
          assert.equal(body.expected_active_version_id, null);
          assert.equal(body.expected_last_event_id, null);
          return route.fulfill({ json: search });
        }
        if (url.pathname === `${base}/synthesis/probe`) {
          assert.equal(body.search_id, search.search_id);
          assert.equal(body.parameter, "footprint_depth_mm");
          assert.equal(body.value_mm, fixture.probe_value);
          assert.deepEqual(body.design, first.design);
          return route.fulfill({ json: probe });
        }
        if (url.pathname === `${base}/synthesis/select`) {
          selectCalls += 1;
          assert.equal(body.user_selected, true);
          assert.deepEqual(body.design, second.design);
          assert.equal(body.search_id, search.search_id);
          // The server saves the preview but the first response is lost.
          saved = true;
          if (selectCalls === 1) return route.abort("connectionreset");
          return route.fulfill({ json: { ...select, replayed: true } });
        }
        if (url.pathname === `${base}/plans/${version.version_id}/activate`) {
          assert.equal(body.user_approved, true);
          return route.fulfill({ json: fixture.activation });
        }
        unexpected.push(`POST ${url.pathname}`);
        return route.fulfill({ status: 500, json: { code: "unexpected" } });
      }
      const replay = new Map([
        ["/api/provider/status", { configured: true }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, project],
        [`${base}/media`, { media: [] }],
        [`${base}/designs/readiness`, fixture.readiness],
        [`${base}/plans`, saved ? fixture.plans_after : fixture.plans_before],
        [`${base}/versions/${version.version_id}`, version],
      ]);
      if (replay.has(url.pathname))
        return route.fulfill({ json: replay.get(url.pathname) });
      // Other panels (fabrication preview etc.) are outside this check.
      return route.fulfill({
        status: 503,
        json: { code: "unavailable", message: "Not part of this fixture" },
      });
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const panel = page.getByRole("region", {
      name: "Search designs from your saved stock",
    });
    await panel
      .getByRole("button", { name: "Search stock-feasible designs" })
      .click();
    const designA = panel.getByRole("article", { name: "Design A" });
    const designB = panel.getByRole("article", { name: "Design B" });
    await designA.waitFor();
    await designB.waitFor();
    assert.equal(await panel.getByRole("article").count(), 2);
    for (const name of ["Support panel", "Base panel", "Rear brace"])
      assert.equal(
        await designA.getByText(name, { exact: true }).count(),
        1,
        name,
      );
    const textA = await designA.innerText();
    assert.match(textA, /Brace \(calculated\)/);
    assert.match(textA, /Needs measurements/);
    assert.match(textA, /Not modeled/);
    assert.match(textA, /Not verified/);
    assert.doesNotMatch(textA, /Fails a modeled check/);
    assert.match(
      await panel.innerText(),
      new RegExp(`Checked ${search.nodes_evaluated} of ${search.nodes_total}`),
    );
    // Search and probe are read-only: only their own POSTs were sent.
    await panel
      .getByRole("button", { name: "Try a size change" })
      .first()
      .click();
    await panel.getByLabel("Dimension").selectOption("footprint_depth_mm");
    await panel
      .getByLabel("New value")
      .selectOption(String(fixture.probe_value));
    await panel.getByRole("button", { name: "Check this change" }).click();
    const changed = panel.getByRole("article", { name: "Changed design" });
    await changed.waitFor();
    assert.match(
      await panel.innerText(),
      /Recalculated pieces: stand-base, stand-brace/,
    );
    assert.deepEqual(
      posts.map(([path]) => path),
      [`${base}/synthesis/search`, `${base}/synthesis/probe`],
    );
    // Choose design B: the first response is lost, the retry reuses the key.
    await panel.getByRole("button", { name: "Use design B" }).click();
    await panel
      .getByRole("button", { name: "Retry saving this design" })
      .click();
    await panel.getByText(/Saved as a proposed plan/).waitFor();
    const selects = posts.filter(([path]) =>
      path.endsWith("/synthesis/select"),
    );
    assert.equal(selects.length, 2);
    assert.equal(selects[0][1].idempotency_key, selects[1][1].idempotency_key);
    assert.equal(
      posts.some(([path]) => path.endsWith("/activate")),
      false,
      "selection must not approve",
    );
    // Approval is the existing, separate transaction.
    const approve = page.getByRole("button", { name: "Approve this plan" });
    await approve.waitFor();
    assert.equal(await approve.isDisabled(), true);
    await page
      .getByLabel("I reviewed this plan and its required physical checks.")
      .check();
    await approve.click();
    await page.waitForFunction(
      () => !document.querySelector(".design-candidates"),
    );
    assert.equal(
      posts.filter(([path]) => path.endsWith("/activate")).length,
      1,
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    assert.equal(overflow, false, `horizontal overflow at ${width}px`);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px search/compare two named designs, read-only probe with regenerated brace, lost-response selection retried with one key, separate explicit approval; replayed SYNTHETIC responses only`,
    );
    await page.context().close();
  }
} finally {
  await browser.close();
}
