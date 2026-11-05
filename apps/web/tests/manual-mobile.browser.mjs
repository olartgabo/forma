// Run against a local Next server. The compiled manual and readiness response come
// from manual-mobile-fixture.py; every API response is replayed from that fixture.
// The failed-check snapshot is injected synthetic UI state, not a persisted
// physical event or server replay. This does not call a provider or establish
// a physical result.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node manual-mobile.browser.mjs <playwright module path> <local web URL> <fixture JSON path>",
  );
const origin = new URL(baseUrl);
if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))
  throw new Error("Use a local web server for intercepted browser tests.");
const { project, version, readiness } = JSON.parse(
  fs.readFileSync(fixturePath, "utf8"),
);
const panels = version.manual.panels;
assert.equal(panels.length, 8, "the compiled manual has eight panels");
for (const panel of panels)
  assert(panel.svg.trimStart().startsWith("<svg"), "panels carry actual SVG");
assert.equal(readiness.project_id, project.id);
assert.equal(project.active_version_id, version.version_id);

const credential = "synthetic-browser-owner";
const base = `/api/projects/${project.id}`;
const failureOperation = panels[7].operation_id;
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : {}),
});

const damagedPart = version.plan.parts[0].id;

// Synthetic server reply to a damage report; not a persisted physical event.
function damaged() {
  return {
    ...progress(false),
    last_event_id: "synthetic-damage",
    status: "needs_review",
    failed_operation_ids: [panels[0].operation_id],
    damaged_part_ids: [damagedPart],
    events: [
      {
        id: "synthetic-damage",
        project_id: project.id,
        version_id: version.version_id,
        operation_id: panels[0].operation_id,
        kind: "damage",
        evidence_ids: [],
        recorded_at: "2026-11-02T12:00:00Z",
        actor: "user",
        observation: "SYNTHETIC torn edge; UI test only",
        verification_state: "failed",
        test_result: null,
      },
    ],
  };
}

function progress(failed) {
  return {
    project_id: project.id,
    version_id: version.version_id,
    last_event_id: failed ? "synthetic-failure" : null,
    status: failed ? "needs_review" : "not_started",
    completed_operation_ids: [],
    failed_operation_ids: failed ? [failureOperation] : [],
    events: [],
    evidence: [],
    material_transactions: [],
    expected_remaining_stock: [],
  };
}

async function scenario(width, failed, extra = null) {
  const damage = extra === "damage";
  const material = extra === "material";
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  const errors = [];
  const unexpected = [];
  const writes = [];
  const damageReports = [];
  const materialReports = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const replay = new Map([
    ["/api/provider/status", { configured: false }],
    ["/api/projects", { projects: [], next_cursor: null }],
    [base, project],
    [`${base}/designs/readiness`, readiness],
    [`${base}/media`, { media: [] }],
    // Guided intake reads these on load; the fixture has no saved photos.
    [`${base}/photo-estimates`, { records: [] }],
    [
      `${base}/recognized-items`,
      {
        project_id: project.id,
        revision: null,
        catalog_version: "material-catalog-v1",
        items: [],
        problems: [],
      },
    ],
    [`${base}/plans`, { plans: [version] }],
    [`${base}/versions/${version.version_id}`, version],
    [`${base}/versions/${version.version_id}/progress`, progress(failed)],
  ]);
  try {
    await context.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(`nonlocal ${url.protocol}//${url.hostname}`);
        await route.abort("blockedbyclient");
        return;
      }
      if (!url.pathname.startsWith("/api/")) {
        if (request.method() === "GET") await route.continue();
        else {
          writes.push(`${request.method()} ${url.pathname}`);
          await route.abort("blockedbyclient");
        }
        return;
      }
      if (
        url.pathname.endsWith("/fabrication") ||
        url.pathname.endsWith("/fabrication/assess")
      ) {
        // The dedicated fabrication browser runner covers these read-only
        // routes. Keep manual/report fallback usable during unavailability.
        await route.fulfill({ status: 503, json: { code: "unavailable" } });
        return;
      }
      if (
        damage &&
        request.method() === "POST" &&
        url.pathname === `${base}/damage`
      ) {
        damageReports.push(request.postDataJSON());
        await route.fulfill({ json: { progress: damaged(), replayed: false } });
        return;
      }
      if (
        material &&
        request.method() === "POST" &&
        url.pathname === `${base}/materials`
      ) {
        materialReports.push(request.postDataJSON());
        await route.fulfill({
          json: { progress: progress(false), replayed: false },
        });
        return;
      }
      if (request.method() !== "GET") {
        writes.push(`${request.method()} ${url.pathname}`);
        await route.fulfill({
          status: 500,
          json: { code: "unexpected_write" },
        });
        return;
      }
      if (!replay.has(url.pathname)) {
        unexpected.push(url.pathname);
        await route.fulfill({ status: 500, json: { code: "unexpected" } });
        return;
      }
      if (request.headers().authorization !== `Bearer ${credential}`) {
        unexpected.push(`unauthenticated ${url.pathname}`);
        await route.fulfill({ status: 401, json: { code: "unauthenticated" } });
        return;
      }
      await route.fulfill({ json: replay.get(url.pathname) });
    });
    await page.goto(`${origin.origin}/?project=${project.id}`);
    await page.evaluate(
      (t) => localStorage.setItem("forma.visitor-token", t),
      credential,
    );
    await page.getByRole("button", { name: "Open workbench" }).click();
    const manual = page.locator(".manual-step");
    await manual.waitFor();
    await manual
      .getByText(failed ? "A check failed." : "No physical work recorded.", {
        exact: false,
      })
      .waitFor();
    if (material) {
      const record = manual.locator(".material-report");
      await record.locator("summary").click();
      const saveMaterial = record.getByRole("button", {
        name: "Save material record",
      });
      await record
        .getByLabel("Material", { exact: true })
        .selectOption("synthetic-tape-stock");
      assert(
        await record.getByLabel("Recovered after discarding").isDisabled(),
        "connectors cannot be recovered",
      );
      await record.getByLabel("Measured length lost (mm)").fill("20");
      await record
        .getByLabel("How did you measure or identify it?")
        .fill("SYNTHETIC ruler reading; UI test only");
      assert(await saveMaterial.isDisabled(), "material needs confirmation");
      await record
        .getByLabel("I handled or measured this material myself.")
        .check();
      await saveMaterial.click();
      await manual
        .getByText("Material record saved. Expected stock now reflects it.")
        .waitFor();
      assert.equal(materialReports.length, 1);
      assert.deepEqual(
        { ...materialReports[0], idempotency_key: "checked" },
        {
          expected_version_id: version.version_id,
          expected_last_event_id: null,
          idempotency_key: "checked",
          operation_id: panels[0].operation_id,
          kind: "waste",
          stock_id: "synthetic-tape-stock",
          region_id: null,
          length_mm: 20,
          observation: "SYNTHETIC ruler reading; UI test only",
          user_confirmed: true,
          photo_ids: [],
        },
      );
      const box = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      assert(box.doc <= box.viewport + 1, JSON.stringify(box));
      assert.deepEqual(writes, [], "only the material record is written");
      assert.deepEqual(errors, [], "the connected components must not crash");
      assert.deepEqual(unexpected, [], "every request is explicitly replayed");
      console.log(`PASS ${width}px synthetic material record is sent exactly`);
      return;
    }
    if (damage) {
      const report = manual.locator(".damage-report");
      await report.locator("summary").click();
      const saveDamage = report.getByRole("button", {
        name: "Save damage report",
      });
      assert(
        await saveDamage.isDisabled(),
        "an empty damage report is blocked",
      );
      await report.getByLabel(damagedPart, { exact: true }).check();
      await report
        .getByLabel("What happened?")
        .fill("SYNTHETIC torn edge; UI test only");
      assert(
        await saveDamage.isDisabled(),
        "damage needs explicit confirmation",
      );
      await report
        .getByLabel("I saw this damage myself and am reporting it as it is.")
        .check();
      await saveDamage.click();
      await manual
        .getByText(`Damage reported on ${damagedPart}.`, { exact: false })
        .waitFor();
      await manual
        .getByText("Damage saved. Stop and review a repair before continuing.")
        .waitFor();
      assert.equal(
        await manual
          .getByRole("button", { name: "Save physical report" })
          .count(),
        0,
        "confirmations pause after damage",
      );
      assert.equal(damageReports.length, 1);
      const sent = damageReports[0];
      assert.match(sent.idempotency_key, /\S/);
      assert.deepEqual(
        { ...sent, idempotency_key: "checked" },
        {
          expected_version_id: version.version_id,
          expected_last_event_id: null,
          idempotency_key: "checked",
          operation_id: panels[0].operation_id,
          part_ids: [damagedPart],
          observation: "SYNTHETIC torn edge; UI test only",
          user_confirmed: true,
          photo_ids: [],
        },
      );
      const box = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      assert(box.doc <= box.viewport + 1, JSON.stringify(box));
      assert.deepEqual(writes, [], "only the damage report is written");
      assert.deepEqual(errors, [], "the connected components must not crash");
      assert.deepEqual(unexpected, [], "every request is explicitly replayed");
      console.log(`PASS ${width}px synthetic damage report pauses the build`);
      return;
    }
    const observations = [];
    for (let i = 0; i < panels.length; i++) {
      const panel = panels[i];
      const operation = version.plan.operations.find(
        (item) => item.id === panel.operation_id,
      );
      await manual
        .getByText(panel.operation_id, { exact: false })
        .first()
        .waitFor();
      assert(
        await manual.getByText(panel.instruction, { exact: true }).isVisible(),
      );
      const text = await manual.innerText();
      for (const tool of panel.tools) assert(text.includes(tool), tool);
      for (const id of panel.part_ids) assert(text.includes(id), id);
      for (const id of panel.checkpoint_ids) {
        const checkpoint = version.plan.checkpoints.find(
          (item) => item.id === id,
        );
        assert(text.includes(checkpoint.description), id);
      }
      const image = manual.locator("img.manual-diagram");
      await image.waitFor();
      assert(await image.evaluate((el) => el.complete && el.naturalWidth > 0));
      assert((await image.getAttribute("alt")).includes(panel.operation_id));
      const box = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      assert(box.doc <= box.viewport + 1, JSON.stringify(box));
      observations.push({ step: i + 1, id: panel.operation_id, box });
      const save = manual.getByRole("button", { name: "Save physical report" });
      if (i === 0) {
        const drawings = manual.getByRole("navigation", {
          name: "Assembly drawings",
        });
        const first = drawings.getByRole("button", {
          name: "Open drawing for step 1",
          exact: true,
        });
        const second = drawings.getByRole("button", {
          name: "Open drawing for step 2",
          exact: true,
        });
        assert.equal(await first.getAttribute("aria-current"), "step");
        await second.press("Enter");
        assert.equal(await second.getAttribute("aria-current"), "step");
        await first.press("Enter");
        assert.equal(await first.getAttribute("aria-current"), "step");
        const colors = manual.getByRole("button", { name: "Blueprint colors" });
        assert.equal(await colors.getAttribute("aria-pressed"), "true");
        await colors.click();
        assert.equal(await colors.getAttribute("aria-pressed"), "false");
        assert.equal(
          await image.evaluate((el) => getComputedStyle(el).filter),
          "none",
        );
        await colors.click();
        const download = manual.getByRole("link", { name: "Download SVG" });
        assert.equal(
          await download.evaluate(async (el) => (await fetch(el.href)).text()),
          panel.svg,
        );
        await manual.getByRole("button", { name: "Enlarge diagram" }).click();
        const region = manual.getByRole("region", {
          name: "Full-size diagram; scroll to inspect dimensions",
        });
        assert(await region.isVisible());
        const cue = manual.locator(".diagram-pan-cue");
        assert(await cue.isVisible());
        assert.equal(
          await region.getAttribute("aria-describedby"),
          await cue.getAttribute("id"),
        );
        await region.focus();
        assert(await region.evaluate((el) => document.activeElement === el));
        // Every part of the enlarged drawing is reachable by keyboard panning.
        const pan = () =>
          region.evaluate((el) => ({
            left: el.scrollLeft,
            client: el.clientWidth,
            scroll: el.scrollWidth,
          }));
        const start = await pan();
        assert(start.scroll > start.client, JSON.stringify(start));
        await region.press("ArrowRight");
        await page.waitForFunction(
          (el) => el.scrollLeft > 0,
          await region.elementHandle(),
        );
        await region.evaluate((el) => {
          el.scrollLeft = el.scrollWidth;
        });
        const end = await pan();
        assert(
          end.left + end.client >= end.scroll - 1,
          JSON.stringify({ start, end }),
        );
        const doc = await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        );
        assert(doc, "the enlarged drawing scrolls inside its frame only");
        observations.push({ step: i + 1, enlarged: { start, end } });
        await manual
          .getByRole("button", { name: "Fit diagram to screen" })
          .click();
        if (!failed) {
          assert(await save.isDisabled());
          assert((await manual.locator(".physical-checks input").count()) > 0);
          await manual
            .getByLabel("What did you do or observe?")
            .fill("SYNTHETIC UI test only");
          await manual
            .getByLabel(
              "I performed this operation or check and am reporting its actual result.",
            )
            .check();
          assert(
            await save.isDisabled(),
            "unchecked required checks block save",
          );
        }
      }
      if (i === 1 && !failed) {
        assert(operation.depends_on.length > 0);
        assert(
          await manual
            .getByText("Confirm these prerequisite operations first:", {
              exact: false,
            })
            .isVisible(),
        );
        assert.equal(await save.count(), 0);
      }
      if (i === panels.length - 1 && failed) {
        assert(
          await manual
            .getByText("A check failed.", { exact: false })
            .isVisible(),
        );
        assert.equal(await save.count(), 0);
        assert(
          await manual
            .getByRole("button", { name: "Diagnose this failure with Muse" })
            .isDisabled(),
        );
      }
      if (i < panels.length - 1) {
        const next = manual.getByRole("button", { name: "Next step" });
        await next.scrollIntoViewIfNeeded();
        const bounds = await next.boundingBox();
        assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
        await next.click();
      }
    }
    await page
      .getByText("Materials and planned quantities", { exact: true })
      .click();
    const materialsText = await page
      .locator(".manual-materials[open]")
      .innerText();
    for (const item of version.manual.bill_of_materials)
      assert(materialsText.includes(item.description), item.description);
    await page
      .getByText(`Planned parts (${version.plan.parts.length})`, {
        exact: true,
      })
      .click();
    const parts = page.locator(".part-files > li");
    assert.equal(await parts.count(), version.plan.parts.length);
    for (const [index, part] of version.plan.parts.entries()) {
      const card = await parts.nth(index).innerText();
      assert(card.includes(part.id));
      assert(
        card.includes(`${part.geometry.width} × ${part.geometry.height} mm`),
      );
      assert(card.includes(part.source_stock_id));
    }
    assert.deepEqual(writes, [], "browsing the manual writes nothing");
    assert.deepEqual(errors, [], "the connected components must not crash");
    assert.deepEqual(unexpected, [], "every request is explicitly replayed");
    console.log(
      `PASS ${width}px ${failed ? "injected synthetic failed-check UI state" : "fresh progress"}: ${panels.length} panels, ${writes.length} writes`,
    );
  } catch (error) {
    console.error({ width, failed, errors, unexpected, writes });
    throw error;
  } finally {
    await context.close();
  }
}

try {
  for (const width of [390, 320]) {
    for (const failed of [false, true]) await scenario(width, failed);
    await scenario(width, false, "damage");
    await scenario(width, false, "material");
  }
} finally {
  await browser.close();
}
