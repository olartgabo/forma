// Real compiler/canonical/API fixture replay. Provider calls and physical reports
// are forbidden; one explicit synthetic measurement save is intercepted locally.
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
      measurementWrites = [],
      analysisRequests = [],
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
      if (
        request.method() === "POST" &&
        mode === "assembled" &&
        url.pathname === `${base}/stability/analyses`
      ) {
        analysisRequests.push(request.postDataJSON());
        assert.equal(
          analysisRequests.length,
          1,
          "only the explicit capture prerequisite analyzes",
        );
        return route.fulfill({ json: fixture.assembled_analysis });
      }
      if (
        request.method() === "POST" &&
        mode === "assembled" &&
        url.pathname === `${base}/stability/measurements`
      ) {
        measurementWrites.push(request.postDataJSON());
        assert.equal(measurementWrites.length, 1);
        assert.deepEqual(
          {
            ...measurementWrites[0],
            idempotency_key: fixture.measurement_body.idempotency_key,
          },
          fixture.measurement_body,
        );
        mode = "measured";
        replay.set(
          `${base}/versions/${version.version_id}/progress`,
          fixture.measured_progress,
        );
        return route.fulfill({ json: fixture.measurement_saved });
      }
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
              : mode === "measured"
                ? fixture.measured_context
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
                : mode === "measured"
                  ? fixture.measured_view
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
    if (width === 390) {
      await canvas.scrollIntoViewIfNeeded();
      await canvas.evaluate((element) => {
        element.dataset.touchCanceled = "0";
        element.addEventListener(
          "pointercancel",
          () => {
            element.dataset.touchCanceled = "1";
          },
          { once: true },
        );
      });
      const touchBox = await canvas.boundingBox();
      const beforeTouch = await canvas
        .locator("polygon")
        .first()
        .getAttribute("points");
      const scrollBefore = await page.evaluate(() => scrollY);
      const cdp = await context.newCDPSession(page);
      const x = touchBox.x + touchBox.width / 2,
        y = touchBox.y + touchBox.height / 2;
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchStart",
        touchPoints: [{ x, y }],
      });
      for (const distance of [20, 40, 60])
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchMove",
          touchPoints: [{ x, y: y + distance }],
        });
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchEnd",
        touchPoints: [],
      });
      await cdp.detach();
      assert.equal(
        await canvas.getAttribute("data-touch-canceled"),
        "0",
        "vertical touch drag is not canceled by browser panning",
      );
      assert.notEqual(
        await canvas.locator("polygon").first().getAttribute("points"),
        beforeTouch,
        "vertical touch tilts the assembly",
      );
      assert.equal(
        await page.evaluate(() => scrollY),
        scrollBefore,
        "canvas drag does not scroll the page",
      );
    }
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
    assert.equal(
      analysisRequests.length,
      0,
      "ordinary camera/selection controls never analyze",
    );
    assert.equal(
      measurementWrites.length,
      0,
      "ordinary camera/selection controls never save measurements",
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
    replay.set(
      `${base}/versions/${version.version_id}/progress`,
      fixture.assembled_progress,
    );
    await viewer
      .getByRole("button", { name: "Refresh assembly view", exact: true })
      .click();
    await viewer
      .getByRole("heading", { name: "User-reported assembled stage" })
      .waitFor();
    await page
      .getByRole("button", { name: "Refresh physical reports", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Analyze stability", exact: true })
      .click();
    const capture = page.getByRole("region", {
      name: "Stability measurements",
    });
    await capture
      .getByRole("button", {
        name: "Record stability measurements",
        exact: true,
      })
      .click();
    const measurements = fixture.measurement_body.measurements;
    const fill = async (name, value) =>
      capture.locator(`[name="${name}"]`).fill(String(value));
    for (const [prefix, body] of [
      ["stand", measurements.stand],
      ...measurements.cases.map((c) => [c.orientation, c.device]),
    ]) {
      await fill(`${prefix}_mass_g`, body.mass_kg * 1000);
      await fill(`${prefix}_mass_resolution_g`, body.mass_resolution_kg * 1000);
      await fill(
        `${prefix}_position_resolution_mm`,
        body.position_resolution_m * 1000,
      );
      for (const axis of ["x", "y", "z"])
        await fill(`${prefix}_${axis}_mm`, body.center_of_mass_m[axis] * 1000);
      await fill(`${prefix}_method`, body.method);
    }
    for (const item of measurements.cases)
      await fill(`${item.orientation}_pose`, item.pose_description);
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
    await canvas.waitFor();
    await viewer.getByRole("button", { name: part, exact: true }).click();
    assert.equal(
      await manualButton.isDisabled(),
      true,
      "measurement edit preserves the existing manual navigation lock",
    );
    const viewsBeforeSave = viewRequests.length;
    await capture
      .getByRole("button", { name: "Save stability measurements", exact: true })
      .click();
    await page.getByText("Measurements saved.", { exact: false }).waitFor();
    await viewer.locator("summary").click();
    await viewer
      .getByText(
        `Evidence revision ${fixture.measured_view.evidence_revision}.`,
        { exact: false },
      )
      .waitFor();
    assert.ok(
      viewRequests.length > viewsBeforeSave,
      "same-page save refreshes an open viewer without a manual refresh",
    );
    const freshParams = new URLSearchParams(viewRequests.at(-1));
    assert.equal(
      freshParams.get("expected_last_event_id"),
      fixture.measured_context.last_event_id,
      "new view request binds the saved measurement history cursor",
    );
    assert.notEqual(
      fixture.measured_view.evidence_revision,
      fixture.assembled_view.evidence_revision,
    );
    assert.equal(analysisRequests.length, 1);
    assert.equal(measurementWrites.length, 1);
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
      `PASS assembly viewer ${width}px: canonical facets, keyboard/pointer${width === 390 ? "/vertical touch" : ""}, zoom/separation, locked manual links, measurement-save cursor/evidence refresh, stale/foreign/unsupported/unavailable fallback, unmount cleanup; camera controls cause zero analysis or writes, one explicit synthetic capture save`,
    );
  }
} finally {
  await browser.close();
}
