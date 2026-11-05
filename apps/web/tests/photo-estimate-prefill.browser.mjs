// Offline intercepted app requests. No provider, deployed project or physical evidence.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const [modulePath, baseUrl] = process.argv.slice(2);
const origin = new URL(baseUrl);
assert.ok(["127.0.0.1", "localhost"].includes(origin.hostname));
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
const unknown = () => ({
  value: null,
  unit: "mm",
  source: "unknown",
  confirmed: false,
});
try {
  for (const width of [390, 1280]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      serviceWorkers: "block",
    });
    const page = await context.newPage();
    const errors = [],
      unexpected = [],
      saved = [],
      measured = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let project = {
      id: "prefill-project",
      goal: "Offline material-size preview",
      revision_id: "inventory-1",
      active_version_id: null,
      inventory_confirmed: false,
      requirements: null,
      stocks: ["sheet-a", "sheet-b"].map((id, i) => ({
        id,
        name: `Sheet ${i + 1}`,
        kind: "sheet",
        material: "cardboard",
        condition: "uncertain",
        width_mm: i
          ? { value: 351, unit: "mm", source: "user_ruler", confirmed: true }
          : unknown(),
        height_mm: unknown(),
        thickness_mm: unknown(),
        remaining_length_mm: unknown(),
        usable_regions: [],
        image_ids: ["photo-one"],
      })),
    };
    const base = `/api/projects/${project.id}`;
    const photo = {
      id: "photo-one",
      project_id: project.id,
      content_type: "image/png",
      byte_count: 100,
      width_px: 640,
      height_px: 480,
      evidence_linked: false,
    };
    const records = [];
    await context.route("**/*", async (route) => {
      const req = route.request(),
        url = new URL(req.url());
      if (url.origin !== origin.origin) {
        unexpected.push(url.origin);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (
        req.method() === "POST" &&
        url.pathname === `${base}/photo-estimates`
      ) {
        const body = req.postDataJSON();
        measured.push(body);
        assert.equal(body.reference.printed_check_x_mm, 150);
        assert.equal(body.capture.same_surface_as_reference, true);
        const record = {
          estimate_id: `estimate-${measured.length}`,
          project_id: project.id,
          created_revision_id: project.revision_id,
          status: "current",
          stale_reasons: [],
          replayed: false,
          estimate: {
            input: body,
            outcome: "estimate",
            measurement_status: "photo_estimate_unconfirmed",
            calibration_status: "uncalibrated",
            method_version: "offline-fixture",
            assumptions: [],
            diagnostics: [],
            dimensions: [
              ["width_mm", "edge_length_mm", 280],
              ["height_mm", "edge_width_mm", 190],
            ].map(([stock_field, name, value]) => ({
              stock_field,
              name,
              value,
              display_value: value,
              display_step: 2,
              sensitivity_low: value - 2,
              sensitivity_high: value + 2,
              unit: "mm",
            })),
          },
        };
        records.push(record);
        return route.fulfill({ json: record });
      }
      if (req.method() === "PUT" && url.pathname === `${base}/inventory`) {
        const body = req.postDataJSON();
        saved.push(body);
        project = {
          ...project,
          stocks: body.stocks,
          requirements: body.requirements,
          inventory_confirmed: true,
          revision_id: "inventory-2",
        };
        return route.fulfill({ json: { project, replayed: false } });
      }
      if (req.method() !== "GET") {
        // The existing post-save question calculation is deterministic and runs
        // only after the explicit inventory save, not while prefilling drafts.
        if (
          req.method() === "POST" &&
          url.pathname === `${base}/measurement-decisions`
        ) {
          assert.equal(saved.length, 1);
          return route.fulfill({
            status: 503,
            json: {
              code: "unavailable",
              message: "Question calculation is outside this fixture",
            },
          });
        }
        unexpected.push(`${req.method()} ${url.pathname}`);
        return route.abort();
      }
      if (url.pathname === `${base}/media/photo-one`)
        return route.fulfill({
          contentType: "image/png",
          body: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
            "base64",
          ),
        });
      const reads = {
        "/api/provider/status": { configured: false },
        "/api/projects": { projects: [], next_cursor: null },
        [base]: project,
        [`${base}/media`]: { media: [photo] },
        [`${base}/plans`]: { plans: [] },
        [`${base}/construction/receipts`]: { receipts: [] },
        [`${base}/recognized-items`]: {
          project_id: project.id,
          revision: null,
          catalog_version: "test",
          items: [],
          problems: [],
          conflicts: [],
          replayed: false,
        },
        [`${base}/photo-estimates`]: { records },
        [`${base}/designs/readiness`]: {
          project_id: project.id,
          inventory_revision_id: project.revision_id,
          status: "needs_input",
          inventory_confirmed: false,
          missing_inputs: ["Measure materials"],
          blockers: [],
        },
      };
      return route.fulfill(
        reads[url.pathname]
          ? { json: reads[url.pathname] }
          : {
              status: 404,
              json: { code: "not_found", message: "Offline fixture" },
            },
      );
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.evaluate(
      (t) => localStorage.setItem("forma.visitor-token", t),
      "offline-owner",
    );
    await page.getByRole("button", { name: "Open workbench" }).click();
    await page.getByRole("button", { name: "Estimate material sizes" }).click();
    await page.getByLabel("Line A, measured (mm)", { exact: true }).fill("150");
    assert.equal(measured.length, 0);
    assert.equal(saved.length, 0);
    for (const id of ["sheet-a", "sheet-b"]) {
      const card = page.locator(`#card-${id}`);
      await card.getByLabel(/This piece is flat/).check();
      await card
        .getByRole("button", { name: "Draw a box", exact: true })
        .click();
      const canvas = card.locator(".guided-canvas svg");
      await canvas.scrollIntoViewIfNeeded();
      const box = await canvas.boundingBox();
      assert.ok(box);
      await page.mouse.move(
        box.x + box.width * 0.15,
        box.y + box.height * 0.15,
      );
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width * 0.65,
        box.y + box.height * 0.65,
        { steps: 4 },
      );
      await page.mouse.up();
      await card
        .getByRole("button", { name: "Measure from photo", exact: true })
        .click();
      await card
        .getByText("Shorter side: 190 mm (photo estimate)", { exact: true })
        .waitFor();
    }
    await page
      .locator("#card-sheet-a")
      .getByText("Longer side: 280 mm (photo estimate)", { exact: true })
      .waitFor();
    await page
      .locator("#card-sheet-b")
      .getByText("Longer side: 351 mm (measured)", { exact: true })
      .waitFor();
    assert.equal(
      saved.length,
      0,
      "measurement must not save inventory automatically",
    );
    assert.equal(measured.length, 2);
    await page
      .getByRole("button", { name: "Save materials", exact: true })
      .click();
    await page.getByText("Materials saved.", { exact: true }).waitFor();
    assert.equal(saved.length, 1);
    assert.deepEqual(saved[0].stocks[0].width_mm, {
      value: 280,
      unit: "mm",
      source: "photo_estimate",
      confirmed: false,
    });
    assert.deepEqual(saved[0].stocks[1].width_mm, {
      value: 351,
      unit: "mm",
      source: "user_ruler",
      confirmed: true,
    });
    assert.equal(saved[0].stocks[0].thickness_mm.value, null);
    assert.equal(saved[0].stocks[1].height_mm.confirmed, false);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log(
    "Photo estimate prefills and explicit save passed at 390px and 1280px; no provider calls.",
  );
} finally {
  await browser.close();
}
