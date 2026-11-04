// Real compiler/canonical/API fixture replay. No provider or physical writes.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node assembly-view.browser.mjs <playwright module> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))
  throw new Error("A local server is required");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { project, version, readiness, progress } = fixture;
const base = `/api/projects/${project.id}`;
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
try {
  for (const width of [390, 1280]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
      reducedMotion: "reduce",
      hasTouch: width === 390,
    });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    const errors = [],
      unexpected = [],
      writes = [],
      viewRequests = [];
    let mode = "ready",
      releaseLate,
      enteredLate;
    const entered = new Promise((resolve) => {
      enteredLate = resolve;
    });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("dialog", (dialog) => dialog.accept());
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
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(url.origin);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() !== "GET") {
        writes.push(request.method() + " " + url.pathname);
        return route.fulfill({
          status: 500,
          json: { code: "unexpected_write" },
        });
      }
      if (url.pathname.endsWith("/fabrication"))
        return route.fulfill({ status: 503, json: { code: "unavailable" } });
      if (url.pathname === `${base}/stability/context`)
        return route.fulfill({
          json:
            mode === "partial"
              ? fixture.partial_context
              : mode === "assembled"
                ? fixture.assembled_context
                : fixture.context,
        });
      if (url.pathname === `${base}/assembly-view`) {
        viewRequests.push(url.search);
        assert.equal(
          url.searchParams.get("expected_inventory_revision_id"),
          project.revision_id,
        );
        assert.equal(
          url.searchParams.get("plan_version_id"),
          version.version_id,
        );
        if (mode === "unavailable" || mode === "stale")
          return route.fulfill({
            status: mode === "stale" ? 409 : 503,
            json: { code: mode },
          });
        if (mode === "late") {
          enteredLate();
          await new Promise((resolve) => {
            releaseLate = resolve;
          });
          if (request.failure()) return;
          return route.fulfill({ json: fixture.view }).catch((error) => {
            if (!/closed|cancel|handled/i.test(error.message)) throw error;
          });
        }
        return route.fulfill({
          json:
            mode === "foreign"
              ? { ...fixture.view, project_id: "foreign" }
              : mode === "partial"
                ? fixture.partial_view
                : mode === "assembled"
                  ? fixture.assembled_view
                  : fixture.view,
        });
      }
      if (!replay.has(url.pathname)) {
        unexpected.push(url.pathname);
        return route.fulfill({ status: 500, json: { code: "unexpected" } });
      }
      return route.fulfill({ json: replay.get(url.pathname) });
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .click();
    const viewer = page.getByRole("region", { name: "Assembly viewer" });
    await viewer
      .getByRole("button", { name: "Open assembly view", exact: true })
      .click();
    const canvas = viewer.getByRole("group", {
      name: "Rotatable nominal assembly",
    });
    await canvas.waitFor();
    assert.equal(
      await canvas.locator("polygon").count(),
      fixture.view.geometry.facets.length,
    );
    assert.equal(viewRequests.length, 1);
    const points = await canvas
      .locator("polygon")
      .first()
      .getAttribute("points");
    await canvas.focus();
    await page.keyboard.press("ArrowRight");
    assert.notEqual(
      await canvas.locator("polygon").first().getAttribute("points"),
      points,
    );
    await viewer.getByLabel("Zoom", { exact: true }).fill("1.2");
    await viewer.getByLabel("Separate parts (display only)").fill("0.6");
    await viewer
      .getByRole("button", { name: "Orbit left", exact: true })
      .click();
    await viewer.getByRole("button", { name: "Tilt up", exact: true }).click();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      box.x + box.width / 2 + 30,
      box.y + box.height / 2 + 20,
    );
    await page.mouse.up();
    assert.equal(
      viewRequests.length,
      1,
      "display controls do not request analyses or geometry",
    );
    const part = fixture.view.geometry.active_part_ids[0];
    await viewer.getByRole("button", { name: part, exact: true }).click();
    assert.equal(
      await viewer
        .getByRole("button", { name: part, exact: true })
        .getAttribute("aria-pressed"),
      "true",
    );
    const operation = fixture.view.operation_parts.find((link) =>
      link.part_ids.includes(part),
    );
    assert.ok(operation);
    const manualButton = viewer.getByRole("button", {
      name: `Show manual operation ${operation.operation_id}`,
      exact: true,
    });
    await manualButton.click();
    await page
      .locator(".manual-step")
      .getByText(operation.operation_id, { exact: true })
      .waitFor();
    assert.equal(
      writes.length,
      0,
      "part selection navigates without completing work",
    );
    assert.ok(
      await viewer.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    );
    await viewer.screenshot({
      path: path.join(os.tmpdir(), `forma-assembly152-${width}.png`),
    });
    for (const bad of ["partial", "unavailable", "stale", "foreign"]) {
      mode = bad;
      await viewer
        .getByRole("button", { name: "Refresh assembly view", exact: true })
        .click();
      const expected =
        bad === "partial"
          ? "This physical stage"
          : bad === "stale"
            ? "The project changed"
            : bad === "foreign"
              ? "Analysis context changed"
              : "The assembly view is unavailable";
      await viewer.getByRole("status").filter({ hasText: expected }).waitFor();
      assert.equal(
        await canvas.count(),
        0,
        "unsupported/stale scenes are removed",
      );
      assert.ok(
        (await page.locator(".manual-step img").count()) > 0,
        "authoritative SVG fallback remains",
      );
    }
    mode = "assembled";
    await viewer
      .getByRole("button", { name: "Refresh assembly view", exact: true })
      .click();
    await viewer
      .getByRole("heading", { name: "User-reported assembled stage" })
      .waitFor();
    mode = "late";
    await viewer
      .getByRole("button", { name: "Refresh assembly view", exact: true })
      .click();
    await entered;
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    releaseLate();
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("group", { name: "Rotatable nominal assembly" })
        .count(),
      0,
      "late response cannot restore an unmounted project",
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(writes, []);
    await context.close();
    console.log(
      `PASS assembly viewer ${width}px: canonical facets, keyboard/pointer, zoom/separation, manual links, stale/foreign/unsupported/unavailable fallback, unmount cleanup, zero physical writes`,
    );
  }
} finally {
  await browser.close();
}
