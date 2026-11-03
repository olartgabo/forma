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
const initialAnalysisContext = {
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
    const analysisContext = { ...initialAnalysisContext };
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    const errors = [],
      unexpected = [],
      analyses = [],
      measurementWrites = [];
    let measurementMode = "normal";
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
          expected_last_event_id: analysisContext.last_event_id,
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
            mode === "assembled"
              ? fixture.assembled_response
              : mode === "measured"
                ? fixture.measured_response
                : mode === "changed-measured"
                  ? fixture.changed_measured_response
                  : mode === "blocked"
                    ? blocked_response
                    : mode === "unknown"
                      ? unknown_response
                      : analytic_response,
        });
      }
      if (
        url.pathname === `${base}/stability/measurements` &&
        request.method() === "POST"
      ) {
        const body = request.postDataJSON();
        measurementWrites.push(body);
        if (measurementMode === "reject")
          return route.fulfill({
            status: 409,
            json: {
              code: "stale_version",
              message: "Synthetic stale measurement rejection",
            },
          });
        const changed = measurementMode === "ambiguous";
        const expectedBody = changed
          ? fixture.changed_measurement_body
          : fixture.measurement_body;
        assert.deepEqual(
          { ...body, idempotency_key: expectedBody.idempotency_key },
          expectedBody,
        );
        const saved = changed
          ? fixture.changed_measurement_saved
          : fixture.measurement_saved;
        analysisContext.last_event_id = saved.last_event_id;
        replay.set(
          `${base}/versions/${version.version_id}/progress`,
          changed
            ? fixture.changed_measured_progress
            : fixture.measured_progress,
        );
        if (changed && measurementWrites.length === 2)
          return route.abort("failed");
        if (changed)
          assert.deepEqual(
            measurementWrites[1],
            body,
            "uncertain retry retains exact body/key/cursor",
          );
        mode = changed ? "changed-measured" : "measured";
        return route.fulfill({ json: { ...saved, replayed: changed } });
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
        .getByText("Status: needs measurement", { exact: true })
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
    await panel
      .getByRole("img", {
        name: "Nominal assembly side view with numbered facets",
      })
      .waitFor();
    await panel
      .getByText("Nominal assembly — planned preview", { exact: true })
      .waitFor();
    await panel
      .getByText("This is not a measured shape", { exact: false })
      .waitFor();
    assert.equal(
      await panel.getByText("Signed margin:", { exact: false }).count(),
      0,
    );
    assert.equal(
      await panel.locator("svg polygon").count(),
      blocked_response.geometry_preview.facets.length,
    );
    const nominalBox = await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    assert(
      nominalBox.scroll <= nominalBox.width + 1,
      JSON.stringify(nominalBox),
    );
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
    // A second path consumes real default measured-adapter replies exported
    // after actual API reports/save/edit operations in a temporary database.
    Object.assign(analysisContext, fixture.assembled_context);
    replay.set(
      `${base}/versions/${version.version_id}/progress`,
      fixture.assembled_progress,
    );
    mode = "assembled";
    await page
      .getByRole("button", { name: "Refresh physical reports", exact: true })
      .click();
    await analyze.click();
    await panel
      .getByText("Nominal assembly — user-reported assembled stage", {
        exact: true,
      })
      .waitFor();
    const capture = panel.getByRole("region", {
      name: "Stability measurements",
    });
    const record = capture.getByRole("button", {
      name: "Record stability measurements",
      exact: true,
    });
    async function enterMeasurements(payload) {
      await record.click();
      const measurements = payload.measurements;
      async function fill(name, value) {
        await capture.locator(`[name="${name}"]`).fill(String(value));
      }
      for (const [prefix, body] of [
        ["stand", measurements.stand],
        ...measurements.cases.map((c) => [c.orientation, c.device]),
      ]) {
        await fill(`${prefix}_mass_g`, body.mass_kg * 1000);
        await fill(
          `${prefix}_mass_resolution_g`,
          body.mass_resolution_kg * 1000,
        );
        await fill(
          `${prefix}_position_resolution_mm`,
          body.position_resolution_m * 1000,
        );
        for (const axis of ["x", "y", "z"])
          await fill(
            `${prefix}_${axis}_mm`,
            body.center_of_mass_m[axis] * 1000,
          );
        await fill(`${prefix}_method`, body.method);
      }
      for (const c of measurements.cases)
        await fill(`${c.orientation}_pose`, c.pose_description);
      for (const name of ["x_min", "x_max", "y_min", "y_max"])
        await fill(
          `contact_${name}_mm`,
          measurements.support[`${name}_m`] * 1000,
        );
      await fill(
        "contact_resolution_mm",
        measurements.support.resolution_m * 1000,
      );
      await fill("contact_method", measurements.support.method);
      await fill("required_margin_mm", measurements.required_margin_m * 1000);
      for (const name of [
        "stand_includes_all_parts_and_connectors",
        "actual_contacts_confirmed",
        "rigid_assembly_assumed",
        "horizontal_surface_confirmed",
        "stationary_device_assumed",
        "gravity_only_assumed",
        "user_confirmed",
      ])
        await capture.locator(`[name="${name}"]`).check();
      const widthState = await page.evaluate(() => ({
        width: innerWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      assert(
        widthState.scroll <= widthState.width + 1,
        JSON.stringify(widthState),
      );
    }
    await enterMeasurements(fixture.measurement_body);
    assert.equal(
      await analyze.isDisabled(),
      true,
      "do not calculate during a measurement edit",
    );
    await capture
      .getByRole("button", { name: "Save stability measurements", exact: true })
      .click();
    await panel.getByText("Measurements saved.", { exact: false }).waitFor();
    await page
      .getByText(
        `Physical report history (${fixture.measured_progress.events.length})`,
        { exact: true },
      )
      .waitFor();
    assert.equal(
      await panel.getByText("Signed margin:", { exact: false }).count(),
      0,
      "save invalidates old report without calculating",
    );
    await analyze.click();
    await panel
      .getByText("Modeled status: modeled pass.", { exact: false })
      .waitFor();
    assert.equal(
      await panel.getByText("Signed margin:", { exact: false }).count(),
      2,
      "both declared cases render",
    );
    await panel.getByText("not conservative", { exact: false }).waitFor();
    measurementMode = "ambiguous";
    await enterMeasurements(fixture.changed_measurement_body);
    assert.equal(
      await panel.getByText("Signed margin:", { exact: false }).count(),
      0,
      "editing invalidates old report",
    );
    await capture
      .getByRole("button", { name: "Save stability measurements", exact: true })
      .click();
    await capture
      .getByText("The save outcome is unknown.", { exact: false })
      .waitFor();
    assert.equal(
      await capture.locator('[name="landscape_x_mm"]').isDisabled(),
      true,
      "unknown write locks editing",
    );
    // Unknown write survives both a component unmount and a full page reload.
    assert.equal(measurementWrites.length, 2);
    await page.getByRole("button", { name: "Disconnect", exact: true }).click();
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .click();
    await capture
      .getByRole("button", {
        name: "Retry the same measurement save",
        exact: true,
      })
      .waitFor();
    assert.equal(
      measurementWrites.length,
      2,
      "remount does not automatically retry",
    );
    assert.equal(
      await capture
        .getByRole("button", {
          name: "Record stability measurements",
          exact: true,
        })
        .count(),
      0,
    );
    await page.reload();
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .click();
    await capture
      .getByRole("button", {
        name: "Retry the same measurement save",
        exact: true,
      })
      .waitFor();
    assert.equal(
      measurementWrites.length,
      2,
      "page reload does not automatically retry",
    );
    assert.equal(await analyze.isDisabled(), true);
    const retainedValues = await page.evaluate(() =>
      Object.entries(localStorage).filter(([key]) =>
        key.startsWith("forma-stability-pending-v1:"),
      ),
    );
    assert.equal(retainedValues.length, 1);
    assert(
      !JSON.stringify(retainedValues).includes("synthetic-browser-owner"),
      "credential never persisted",
    );
    assert.deepEqual(
      JSON.parse(retainedValues[0][1]).payload,
      measurementWrites[1],
    );
    await capture
      .getByRole("button", {
        name: "Retry the same measurement save",
        exact: true,
      })
      .click();
    await panel.getByText("Measurements saved.", { exact: false }).waitFor();
    await page
      .getByText(
        `Physical report history (${fixture.changed_measured_progress.events.length})`,
        { exact: true },
      )
      .waitFor();
    await analyze.click();
    await panel
      .getByText("Modeled status: modeled fail.", { exact: false })
      .waitFor();
    assert.equal(
      await panel.getByText("Signed margin:", { exact: false }).count(),
      2,
    );
    measurementMode = "reject";
    await enterMeasurements({
      ...fixture.changed_measurement_body,
      expected_last_event_id: fixture.changed_measurement_saved.last_event_id,
    });
    await page.evaluate(() => {
      window.__originalStorageSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (key.startsWith("forma-stability-pending-v1:"))
          throw new Error("Synthetic recovery storage unavailable");
        return window.__originalStorageSetItem.call(this, key, value);
      };
    });
    await capture
      .getByRole("button", { name: "Save stability measurements", exact: true })
      .click();
    await capture
      .getByText("Synthetic recovery storage unavailable", { exact: true })
      .waitFor();
    assert.equal(
      measurementWrites.length,
      3,
      "storage failure prevents the network write",
    );
    await page.evaluate(() => {
      Storage.prototype.setItem = window.__originalStorageSetItem;
      delete window.__originalStorageSetItem;
    });
    await capture
      .getByRole("button", {
        name: "Check recovery storage again",
        exact: true,
      })
      .click();
    await capture.locator('[name="stand_mass_g"]:enabled').waitFor();
    await capture
      .getByRole("button", { name: "Save stability measurements", exact: true })
      .click();
    await capture.getByText("The project changed.", { exact: false }).waitFor();
    assert.equal(
      await capture.locator('[name="stand_mass_g"]').isDisabled(),
      true,
    );
    await capture
      .getByRole("button", { name: "Reload measurement context", exact: true })
      .click();
    await capture.locator('[name="stand_mass_g"]:enabled').waitFor();
    assert.equal(
      await capture.locator('[name="user_confirmed"]').isChecked(),
      false,
      "fresh context requires confirmation again",
    );
    await capture
      .getByRole("button", { name: "Cancel measurement entry", exact: true })
      .click();
    assert.equal(
      measurementWrites.length,
      4,
      "one save, uncertain save and exact retry, stale rejection",
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
    assert.equal(analyses.length, 9);
    console.log(
      `PASS ${width}px canonical nominal geometry, measurement blockers, computed overlay, history invalidation, stale error, unknown input, actual measured save/recalculate/edit/durable retry/stale flow, late cancellation; ${analyses.length} analysis requests`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
