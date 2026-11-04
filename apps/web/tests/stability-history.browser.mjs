// Replays actual API responses exported by stability-history-fixture.py in a local
// intercepted browser. Offline scripted MetaMuse; no provider or physical pass.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node stability-history.browser.mjs <playwright> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("Only a local intercepted browser is permitted");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { project, version, readiness, progress, context, history, comparison } =
  fixture;
const base = `/api/projects/${project.id}`;
const [current, old] = history.reports;
const short = (id) => id.slice("stability-report-".length, 29);
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
    const writes = [];
    const musePosts = [];
    let holdHistory = true;
    let failNextHistory = false;
    let historyAfterChange = false;
    page.on("pageerror", (e) => errors.push(e.message));
    const replay = new Map([
      ["/api/provider/status", { configured: true }],
      ["/api/projects", { projects: [], next_cursor: null }],
      [base, project],
      [`${base}/media`, { media: [] }],
      [`${base}/designs/readiness`, readiness],
      [`${base}/plans`, { plans: [version] }],
      [`${base}/versions/${version.version_id}`, version],
      [`${base}/versions/${version.version_id}/progress`, progress],
      [`${base}/stability/reports/${old.report_id}`, fixture.old_detail],
      [`${base}/stability/reports/${current.report_id}`, fixture.new_detail],
    ]);
    await page.context().route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(`external ${url.origin}`);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const method = request.method();
      if (
        method === "GET" &&
        url.pathname === `${base}/versions/${version.version_id}/fabrication`
      )
        return route.fulfill({
          status: 503,
          json: { code: "unavailable", message: "No fabrication fixture" },
        });
      if (method === "GET" && url.pathname === `${base}/stability/context`)
        return route.fulfill({ json: context });
      if (method === "GET" && url.pathname === `${base}/stability/reports`) {
        if (holdHistory) {
          // First history load is held open so the Stop control is exercised.
          holdHistory = false;
          await new Promise((resolve) => setTimeout(resolve, 5000));
          return route.abort().catch(() => {});
        }
        if (failNextHistory) {
          failNextHistory = false;
          return route.fulfill({
            status: 503,
            json: { code: "unavailable", message: "Synthetic outage" },
          });
        }
        return route.fulfill({
          json: historyAfterChange ? fixture.history_after_change : history,
        });
      }
      if (
        method === "GET" &&
        url.pathname === `${base}/stability/report-comparison`
      ) {
        assert.equal(url.searchParams.get("first"), current.report_id);
        assert.equal(url.searchParams.get("second"), old.report_id);
        return route.fulfill({ json: comparison });
      }
      if (method === "POST" && url.pathname === `${base}/stability/reports`) {
        const body = request.postDataJSON();
        writes.push(["save", body]);
        assert.equal(body.expected_last_event_id, context.last_event_id);
        assert.equal(body.plan_version_id, version.version_id);
        assert.match(body.idempotency_key, /^stability-/);
        return route.fulfill({ json: fixture.save });
      }
      if (
        method === "POST" &&
        url.pathname === `${base}/stability/muse-explanations`
      ) {
        const body = request.postDataJSON();
        writes.push(["muse", body]);
        assert.equal(body.provider_context_consented, true);
        assert.equal(body.mode, "analyze_current");
        assert.equal(body.report_id, null);
        assert.equal("measurements" in body, false);
        musePosts.push(body);
        // The server completes the first POST, but its response is lost.
        if (musePosts.length === 1) return route.abort("connectionreset");
        // Then an error without a code, then a 2xx that is not a valid answer.
        if (musePosts.length === 2)
          return route.fulfill({
            status: 500,
            json: { message: "Proxy error" },
          });
        if (musePosts.length === 3)
          return route.fulfill({
            json: { ...fixture.muse_replay, physical_status: "verified" },
          });
        return route.fulfill({ json: fixture.muse_replay });
      }
      if (method === "GET" && replay.has(url.pathname))
        return route.fulfill({ json: replay.get(url.pathname) });
      unexpected.push(`${method} ${url.pathname}`);
      return route.abort();
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const panel = page.getByRole("region", { name: "Saved stability reports" });
    await panel.waitFor();
    assert.deepEqual(writes, [], "mount never saves or asks automatically");

    await panel
      .getByRole("button", { name: "Load report history", exact: true })
      .click();
    await panel.getByRole("button", { name: "Stop", exact: true }).click();
    await panel.getByText("Request stopped", { exact: false }).waitFor();
    assert.equal(
      await panel.getByRole("list", { name: "Report history" }).count(),
      0,
    );

    await panel
      .getByRole("button", { name: "Save current calculation", exact: true })
      .click();
    await panel
      .getByText(
        `Saved report ${short(current.report_id)} — ${fixture.save.saved.report_status.replaceAll("_", " ")}.`,
        { exact: true },
      )
      .waitFor();
    const list = panel.getByRole("list", { name: "Report history" });
    await list.waitFor();
    assert.equal(await list.getByRole("listitem").count(), 2);
    await list.getByText("Current", { exact: true }).waitFor();
    await list
      .getByText("Stale — build history or measurements changed", {
        exact: true,
      })
      .waitFor();

    await panel
      .getByRole("button", { name: `View report ${short(old.report_id)}` })
      .click();
    const detail = panel.getByRole("article", { name: "Saved report detail" });
    await detail
      .getByText("Historical report — stale because build history", {
        exact: false,
      })
      .waitFor();
    await detail.getByText("Shown read-only.", { exact: false }).waitFor();

    const compare = panel.getByRole("button", {
      name: "Compare two selected reports",
    });
    assert.equal(await compare.isDisabled(), true);
    const boxes = list.getByRole("checkbox");
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await compare.click();
    const result = panel.getByRole("article", { name: "Report comparison" });
    await result
      .getByText("compared check by check only", { exact: false })
      .waitFor();
    const text = await result.innerText();
    assert.match(text, /portrait — tip: .*equal within tolerance/);
    assert.doesNotMatch(text, /winner|best|ranked/i);

    const ask = panel.getByRole("button", { name: "Ask MetaMuse to explain" });
    await boxes.nth(0).uncheck();
    await boxes.nth(1).uncheck();
    assert.equal(await ask.isDisabled(), true, "consent is required first");
    await panel
      .getByLabel("Share this stability report (no photos) with MetaMuse")
      .check();
    await ask.click();
    await panel
      .getByText("The connection failed before a response arrived", {
        exact: false,
      })
      .waitFor();
    const retry = panel.getByRole("button", {
      name: "Retry the same MetaMuse request",
    });
    await retry.waitFor();
    assert.equal(await ask.count(), 0, "a new request cannot be started");
    // Unclassified failures keep the request instead of releasing its key.
    await retry.click();
    await panel.getByText("are unavailable", { exact: false }).waitFor();
    await retry.click();
    await panel
      .getByText("invalid MetaMuse explanation", { exact: false })
      .waitFor();
    await retry.waitFor();
    assert.equal(await ask.count(), 0, "still only the same request");

    // The retained request survives a reload of the page.
    await page.reload();
    const credential = page.getByLabel("Owner credential");
    if (await credential.count()) {
      await credential.fill("synthetic-browser-owner");
      await page.getByRole("button", { name: "Open workbench" }).click();
    }
    await panel.waitFor();
    await retry.waitFor();
    await panel
      .getByRole("button", { name: "Load report history", exact: true })
      .click();
    await list.waitFor();
    await panel
      .getByRole("button", { name: `View report ${short(current.report_id)}` })
      .click();
    await detail
      .getByText("Current for this plan, inventory and history.", {
        exact: true,
      })
      .waitFor();

    // Another tab changes measurements; the history refresh after the
    // answer then fails once.
    historyAfterChange = true;
    failNextHistory = true;
    await retry.click();
    const answer = panel.getByRole("article", {
      name: "MetaMuse stability explanation",
    });
    await answer
      .getByText(fixture.muse_replay.explanation.summary, { exact: true })
      .waitFor();
    await answer
      .getByText("Stale — build history or measurements changed", {
        exact: false,
      })
      .waitFor();
    await panel
      .getByText("Your result is kept below", { exact: false })
      .waitFor();
    assert.equal(musePosts.length, 4);
    for (const post of musePosts.slice(1))
      assert.deepEqual(post, musePosts[0], "the exact request is resent");
    await panel
      .getByRole("button", { name: "Ask MetaMuse to explain" })
      .waitFor();

    // Reloading history re-judges every open view.
    assert.equal(
      await detail.getByText("Current for this plan", { exact: false }).count(),
      1,
    );
    await panel
      .getByRole("button", { name: "Load report history", exact: true })
      .click();
    await detail
      .getByText("Historical report — stale because build history", {
        exact: false,
      })
      .waitFor();
    assert.equal(await list.getByText("Current", { exact: true }).count(), 0);
    await answer.getByText("Stale —", { exact: false }).waitFor();
    assert.deepEqual(
      writes.map(([kind]) => kind),
      ["save", "muse", "muse", "muse", "muse"],
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    assert.equal(overflow, false, `no horizontal scroll at ${width}px`);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px saved report, history with stale entry, read-only detail, check-by-check comparison, lost, code-less and invalid MetaMuse responses retried with the same request after reload, kept answer on refresh failure, open views re-judged after another tab's measurement change, stopped request`,
    );
    await page.context().close();
  }
} finally {
  await browser.close();
}
