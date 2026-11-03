// Replay actual synthetic API/compiler outputs in the retained PR154 panel.
// Unexpected requests, providers and physical mutations fail. No physical pass.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node fabrication.browser.mjs <playwright module> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))
  throw new Error("A local server is required");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);

try {
  for (const width of [390, 320]) {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(30_000);
    const errors = [],
      unexpected = [],
      assessments = [],
      simulations = [];
    let shown = fixture,
      history = fixture.progress,
      mode = "ready";
    let releaseDelayed, startDelayed;
    const delayed = new Promise((resolve) => {
      releaseDelayed = resolve;
    });
    const started = new Promise((resolve) => {
      startDelayed = resolve;
    });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("dialog", (dialog) => dialog.accept());

    function currentReport() {
      if (history.last_event_id === shown.after_join_progress.last_event_id)
        return shown.after_join_report;
      if (history.last_event_id === shown.repair_progress.last_event_id)
        return shown.repair_report;
      return shown.report;
    }

    await context.route("**/*", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      const base = `/api/projects/${shown.project.id}`,
        version = shown.version;
      if (url.origin !== origin.origin) {
        unexpected.push("nonlocal request");
        await route.abort();
        return;
      }
      if (!url.pathname.startsWith("/api/")) {
        if (request.method() === "GET") await route.continue();
        else {
          unexpected.push(`mutation ${url.pathname}`);
          await route.abort();
        }
        return;
      }
      if (
        url.pathname !== "/api/provider/status" &&
        request.headers().authorization !== "Bearer synthetic-owner"
      ) {
        unexpected.push(`authorization ${url.pathname}`);
        await route.fulfill({ status: 401, json: { code: "unauthorized" } });
        return;
      }
      if (
        url.pathname ===
        `${base}/versions/${version.version_id}/fabrication/assess`
      ) {
        assert.equal(request.method(), "POST");
        const body = request.postDataJSON();
        assessments.push(body);
        assert.deepEqual(body, {
          expected_inventory_revision_id: shown.project.revision_id,
          expected_last_event_id: history.last_event_id,
          additional_tools: ["scissors"],
          tools_confirmed: true,
          ...(history.last_event_id
            ? {
                connector_measurements: shown.connector_measurements,
                remaining_confirmed: true,
              }
            : {}),
        });
        await route.fulfill({
          json: history.last_event_id
            ? shown.measured_report
            : shown.tools_report,
        });
        return;
      }
      if (
        url.pathname === `${base}/versions/${version.version_id}/fabrication`
      ) {
        assert.equal(request.method(), "GET");
        if (mode === "stale") {
          await route.fulfill({
            status: 409,
            json: { code: "stale_version", message: "private server text" },
          });
          return;
        }
        if (mode === "unavailable") {
          await route.fulfill({ status: 503, json: { code: "unavailable" } });
          return;
        }
        const report = currentReport();
        if (mode === "delayed") {
          startDelayed();
          await delayed;
          await route
            .fulfill({
              json: {
                ...report,
                status: "history_conflict",
                blockers: [
                  {
                    code: "stale_version",
                    message: "STALE PROJECT RESULT",
                    target_ids: [],
                  },
                ],
              },
            })
            .catch(() => {});
          return;
        }
        await route.fulfill({
          json:
            mode === "foreign"
              ? {
                  ...report,
                  snapshot: {
                    ...report.snapshot,
                    project_id: "foreign-project",
                  },
                }
              : report,
        });
        return;
      }
      if (url.pathname === `${base}/adapt/simulate`) {
        assert.equal(request.method(), "POST");
        const body = request.postDataJSON();
        simulations.push(body);
        assert.equal(body.expected_version_id, version.version_id);
        assert.equal(body.expected_last_event_id, history.last_event_id);
        assert.equal(body.remaining_confirmed, true);
        assert.equal(body.candidates[0].kind, "replace_part");
        assert.equal(body.candidates[0].target_id, "stand-brace");
        assert.equal(
          body.candidates[0].replacement_stock_id,
          "synthetic-spare",
        );
        await route.fulfill({ json: shown.previews });
        return;
      }
      if (
        url.pathname ===
        `${base}/adapt/previews/${shown.previews.previews[0].preview_id}/fabrication`
      ) {
        assert.equal(request.method(), "GET");
        await route.fulfill({ json: shown.preview_report });
        return;
      }
      if (request.method() !== "GET") {
        unexpected.push(`mutation ${request.method()} ${url.pathname}`);
        await route.abort();
        return;
      }
      const reads = new Map([
        ["/api/provider/status", { configured: false }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, shown.project],
        [`${base}/designs/readiness`, shown.readiness],
        [`${base}/media`, { media: [] }],
        [`${base}/plans`, { plans: [version] }],
        [`${base}/versions/${version.version_id}`, version],
        [`${base}/versions/${version.version_id}/progress`, history],
      ]);
      if (!reads.has(url.pathname)) {
        unexpected.push(`read ${url.pathname}`);
        await route.fulfill({ status: 500, json: { code: "unexpected" } });
        return;
      }
      await route.fulfill({ json: reads.get(url.pathname) });
    });
    try {
      await page.goto(`${origin.origin}/?project=${shown.project.id}`);
      await page.getByLabel("Owner credential").fill("synthetic-owner");
      await page.getByRole("button", { name: "Open workbench" }).click();
      // Locate by retained accessible heading so layout nesting remains free.
      const activePanel = page.getByRole("region", {
        name: "Next step check",
        exact: true,
      });
      await activePanel
        .getByText("No step can be attempted yet.", { exact: true })
        .waitFor();
      await activePanel
        .getByLabel("Additional available tools, one per line")
        .fill("scissors");
      const assess = activePanel.getByRole("button", {
        name: "Assess with my confirmed inputs",
      });
      assert(await assess.isDisabled());
      await activePanel
        .getByLabel("I checked these tools are available for this report.")
        .check();
      await assess.click();
      await activePanel
        .getByText("Cut the labelled panels (stand-cut-panels)", {
          exact: false,
        })
        .first()
        .waitFor();
      await activePanel
        .getByRole("button", { name: "Refresh step check" })
        .focus();
      await page.keyboard.press("Enter");
      await activePanel
        .getByText("No step can be attempted yet.", { exact: true })
        .waitFor();
      mode = "stale";
      await activePanel
        .getByRole("button", { name: "Refresh step check" })
        .click();
      await activePanel
        .getByRole("alert")
        .filter({ hasText: "Reload the manual" })
        .waitFor();
      assert.equal(
        await activePanel
          .getByText("A step can be attempted now.", { exact: true })
          .count(),
        0,
      );
      mode = "foreign";
      await activePanel
        .getByRole("button", { name: "Refresh step check" })
        .click();
      await activePanel
        .getByRole("alert")
        .filter({ hasText: "different project" })
        .waitFor();
      mode = "unavailable";
      await activePanel
        .getByRole("button", { name: "Refresh step check" })
        .click();
      await activePanel.getByRole("alert").waitFor();
      mode = "ready";
      history = shown.after_join_progress;
      await page
        .getByRole("button", { name: "Refresh physical reports", exact: true })
        .click();
      const length = activePanel.getByLabel(
        "Measured remaining synthetic-tape-stock (mm)",
      );
      await length.fill(
        String(shown.connector_measurements[0].remaining_length_mm),
      );
      await activePanel
        .getByLabel("Additional available tools, one per line")
        .fill("scissors");
      assert(await assess.isDisabled());
      await activePanel
        .getByLabel(
          "I measured these remaining lengths myself for this report.",
        )
        .check();
      await activePanel
        .getByLabel("I checked these tools are available for this report.")
        .check();
      await assess.click();
      await activePanel
        .getByText(/\(stand-joint-rear-attach\)/)
        .first()
        .waitFor();
      await activePanel
        .getByRole("button", { name: "Show this step in the manual" })
        .click();
      await page
        .locator(".manual-step h3")
        .filter({ hasText: "Step 5 of 8" })
        .waitFor();
      await activePanel
        .getByRole("button", { name: "Clear report confirmations" })
        .click();
      await length.waitFor();
      assert.equal(await length.inputValue(), "");
      assert.equal(
        await activePanel
          .getByRole("button", { name: "Assess with my confirmed inputs" })
          .isDisabled(),
        true,
      );
      mode = "delayed";
      await activePanel
        .getByRole("button", { name: "Refresh step check" })
        .click();
      await started;
      await page
        .getByRole("button", { name: "Start another project", exact: true })
        .click();
      shown = fixture.second;
      history = shown.progress;
      mode = "ready";
      await page
        .getByLabel("Project ID", { exact: true })
        .fill(shown.project.id);
      await page
        .getByRole("button", { name: "Open project", exact: true })
        .click();
      await activePanel
        .getByText("No step can be attempted yet.", { exact: true })
        .waitFor();
      releaseDelayed();
      await page.waitForTimeout(100);
      assert.equal(
        await page.getByText("STALE PROJECT RESULT", { exact: true }).count(),
        0,
      );
      assert.equal(
        await activePanel
          .getByLabel("Additional available tools, one per line")
          .inputValue(),
        "",
      );
      history = shown.repair_progress;
      await page
        .getByRole("button", { name: "Refresh physical reports", exact: true })
        .click();
      await activePanel
        .getByText(/\(stand-inspect-fit\)/)
        .first()
        .waitFor();
      const repair = page.locator("#repair-review");
      await repair.getByRole("button", { name: "Review a repair" }).click();
      await repair
        .getByRole("combobox", { name: /^Repair/ })
        .selectOption("replace_part");
      await repair
        .getByRole("combobox", { name: /^Part/ })
        .selectOption("stand-brace");
      await repair
        .getByLabel("Replacement stock")
        .selectOption("synthetic-spare");
      await repair
        .getByLabel("What went wrong", { exact: true })
        .fill(shown.previews.previews[0].patch.rationale);
      await repair.getByRole("button", { name: "Add candidate" }).click();
      await repair
        .getByLabel(/Measured remaining tape on synthetic-tape-stock/)
        .fill("260");
      await repair.getByLabel(/I checked the remaining materials/).check();
      await repair
        .getByRole("button", { name: "Simulate repairs", exact: true })
        .click();
      const preview = page.getByRole("region", {
        name: "If approved, next step",
        exact: true,
      });
      await preview
        .getByText(new RegExp(shown.preview_report.next_operation_id))
        .first()
        .waitFor();
      assert.equal(
        await preview.locator("form").count(),
        0,
        "preview uses saved confirmed simulation inputs",
      );
      const size = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      assert(size.document <= size.viewport + 1, JSON.stringify(size));
      assert.equal(assessments.length, 2);
      assert.equal(simulations.length, 1);
      assert.deepEqual(errors, []);
      assert.deepEqual(unexpected, []);
      assert.equal(
        await page.getByText("private server text", { exact: false }).count(),
        0,
      );
      console.log(
        `PASS ${width}px combined tools/measurement confirmations, navigation, stale/error/foreign, withdrawal, delayed project switch and repair preview; zero physical writes`,
      );
    } finally {
      releaseDelayed();
      await context.close();
    }
  }
} finally {
  await browser.close();
}
