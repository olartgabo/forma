// Real API-generated analytic replies, intercepted in a local browser. No provider
// or physical observations. See stability-fixture.py for fixture provenance.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node stability-report.browser.mjs <playwright> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("Only a local intercepted browser is permitted");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const {
  project,
  version,
  readiness,
  analytic_response,
  blocked_response,
  unknown_response,
} = fixture;
const base = `/api/projects/${project.id}`;
const analysisContext = {
  project_id: project.id,
  plan_version_id: version.version_id,
  inventory_revision_id: project.revision_id,
  last_event_id: null,
};
const progress = {
  project_id: project.id,
  version_id: version.version_id,
  last_event_id: null,
  status: "not_started",
  completed_operation_ids: [],
  failed_operation_ids: [],
  events: [],
  evidence: [],
  material_transactions: [],
  expected_remaining_stock: [],
};
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
try {
  for (const width of [390, 1280]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    const errors = [],
      unexpected = [],
      analyses = [];
    let mode = "blocked";
    let releaseLate;
    let lateEntered;
    const entered = new Promise((resolve) => {
      lateEntered = resolve;
    });
    page.on("pageerror", (e) => errors.push(e.message));
    const replay = new Map([
      ["/api/provider/status", { configured: false }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, project],
      [`${base}/media`, { media: [] }],
      [`${base}/designs/readiness`, readiness],
      [`${base}/plans`, { plans: [version] }],
      [`${base}/versions/${version.version_id}`, version],
      [`${base}/versions/${version.version_id}/progress`, progress],
    ]);
    await context.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(`external ${url.origin}`);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (
        url.pathname === `${base}/stability/context` &&
        request.method() === "GET"
      ) {
        assert.equal(
          url.searchParams.get("plan_version_id"),
          version.version_id,
        );
        return route.fulfill({ json: analysisContext });
      }
      if (
        url.pathname === `${base}/stability/analyses` &&
        request.method() === "POST"
      ) {
        const body = request.postDataJSON();
        analyses.push(body);
        assert.deepEqual(body, {
          plan_version_id: version.version_id,
          expected_inventory_revision_id: project.revision_id,
          expected_last_event_id: null,
        });
        if (mode === "error") return route.abort("failed");
        if (mode === "late") {
          lateEntered();
          await new Promise((resolve) => {
            releaseLate = resolve;
          });
          try {
            await route.fulfill({ json: analytic_response });
          } catch {
            /* request intentionally cancelled by unmount */
          }
          return;
        }
        return route.fulfill({
          json:
            mode === "blocked"
              ? blocked_response
              : mode === "unknown"
                ? unknown_response
                : analytic_response,
        });
      }
      if (request.method() === "GET" && replay.has(url.pathname))
        return route.fulfill({ json: replay.get(url.pathname) });
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const panel = page.getByRole("region", { name: "Stability analysis" });
    await panel.waitFor();
    await page
      .getByText("No physical work recorded.", { exact: false })
      .waitFor();
    assert.equal(analyses.length, 0, "mount never computes automatically");
    const analyze = panel.getByRole("button", {
      name: "Analyze stability",
      exact: true,
    });
    await analyze.click();
    try {
      await panel
        .getByText("Status: needs geometry", { exact: true })
        .waitFor();
    } catch (error) {
      console.error({
        panel: await panel.innerText(),
        analyses,
        errors,
        unexpected,
      });
      throw error;
    }
    assert.equal(await panel.locator("svg").count(), 0);
    mode = "analytic";
    await analyze.click();
    await panel
      .getByText("Modeled status: modeled pass.", { exact: false })
      .waitFor();
    await panel.getByRole("img").waitFor();
    await panel.getByText("Signed margin:", { exact: false }).waitFor();
    await panel
      .getByText("unsupported / not evaluated", { exact: false })
      .waitFor();
    await panel
      .getByText("Modeled calculations; physical verification is separate.", {
        exact: true,
      })
      .waitFor();
    assert.equal(analyses.length, 2);
    await page
      .getByRole("button", { name: "Refresh physical reports", exact: true })
      .click();
    await panel.getByRole("img").waitFor({ state: "detached" });
    assert.equal(
      analyses.length,
      2,
      "history refresh invalidates without automatically recalculating",
    );
    await analyze.click();
    await panel.getByRole("img").waitFor();
    const box = await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    assert(box.scroll <= box.width + 1, JSON.stringify(box));
    mode = "error";
    await analyze.click();
    await panel.getByRole("alert").waitFor();
    await panel.getByText("Historical report", { exact: false }).waitFor();
    mode = "unknown";
    await analyze.click();
    await panel
      .getByText("Status: needs measurement", { exact: true })
      .waitFor();
    assert.equal(
      await panel.locator("svg").count(),
      0,
      "unknown inputs cannot retain success overlay",
    );
    mode = "late";
    await analyze.click();
    await entered;
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    releaseLate();
    await page.getByRole("button", { name: "Open workbench" }).waitFor();
    assert.equal(
      await page.getByRole("region", { name: "Stability analysis" }).count(),
      0,
    );
    assert.deepEqual(errors, [], "no browser crashes");
    assert.deepEqual(
      unexpected,
      [],
      "no unapproved API writes or provider requests",
    );
    assert.equal(analyses.length, 6);
    console.log(
      `PASS ${width}px missing geometry, computed overlay, history invalidation, stale error, unknown input, late cancellation; ${analyses.length} analysis requests`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
