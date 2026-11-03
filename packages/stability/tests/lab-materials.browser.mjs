// The optional fixture is software input, never a recorded physical test.
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { chromium } = await import(pathToFileURL(process.argv[2]).href);
const base = process.argv[3] ?? "http://127.0.0.1:3041";
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname));
const fixture = process.env.LAB_RESOURCE_FIXTURE
  ? JSON.parse(await readFile(process.env.LAB_RESOURCE_FIXTURE, "utf8"))
  : null;
const browser = await chromium.launch({
  executablePath: process.env.LAB_BROWSER_PATH,
});
try {
  for (const width of [390, 1280]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    async function generate() {
      const pending = page.waitForResponse((r) =>
        r.url().endsWith("/generate-construction"),
      );
      await page.locator("#construction-generate").click();
      const response = await pending;
      assert.equal(response.status(), 200, await response.text());
      const value = await response.json();
      await page.waitForFunction(() =>
        document
          .querySelector("#construction-status")
          .textContent.includes("steps generated"),
      );
      return value;
    }
    assert.equal(
      await page.locator("#construction-invented-stock").isChecked(),
      false,
    );
    assert.equal(await page.locator("#materials-stocks fieldset").count(), 0);
    assert.equal(await page.locator("#construction-sides").isVisible(), false);
    assert.equal(await page.locator("#construction-sides").isDisabled(), true);
    const empty = await generate();
    assert.equal(empty.fabrication_basis, "supplied_materials_unverified");
    assert.equal(empty.fabrication_plan, null);
    assert.ok(empty.fabrication_blockers.length);
    assert.ok(
      empty.construction.request.target.snapshot.parts.every(
        (p) => p.mass_kg === null,
      ),
    );
    await page.locator("#materials-add-sheet").click();
    let card = page.locator("#materials-stocks fieldset").first();
    await card.getByLabel("Width (mm)", { exact: true }).fill("100");
    await card.getByLabel("Width (mm)", { exact: true }).blur();
    await card.getByLabel("Depth (mm)", { exact: true }).fill("50");
    await card.getByLabel("Depth (mm)", { exact: true }).blur();
    const unknown = await generate();
    assert.equal(unknown.request.resources.stocks[0].thickness_mm.value, null);
    assert.equal(unknown.request.resources.stocks[0].width_mm.confirmed, false);
    assert.equal(unknown.fabrication_plan, null);
    await page.locator("#construction-pieces summary").click();
    const piece = unknown.construction.piece_catalog[0];
    const hostile = '<img src=x onerror="window.badName=true"> 左側';
    await page
      .locator(`[data-piece-id="${piece.part_id}"] input`)
      .fill(hostile);
    await page.locator(`[data-piece-id="${piece.part_id}"] input`).blur();
    const renamed = await generate();
    const renamedPiece = renamed.construction.piece_catalog.find(
      (p) => p.part_id === piece.part_id,
    );
    assert.equal(renamedPiece.reference, piece.reference);
    assert.equal(renamedPiece.display_name, hostile);
    assert.equal(renamedPiece.annotation.source, "user");
    await page.locator("#assembly-stages button").last().click();
    assert.match(
      await page.locator("#assembly-view").textContent(),
      new RegExp(piece.reference),
    );
    assert.ok(
      (await page.locator("#assembly-view").textContent()).includes(hostile),
    );
    assert.equal(await page.locator("#assembly-view img").count(), 0);
    assert.equal(await page.evaluate(() => window.badName), undefined);
    const callouts = [...renamed.construction.piece_catalog].sort((a, b) =>
      a.part_id < b.part_id ? -1 : a.part_id > b.part_id ? 1 : 0,
    );
    for (const [index, entry] of callouts.entries()) {
      const marker = page
        .locator(`#assembly-view svg g[data-piece-id="${entry.part_id}"]`)
        .first();
      assert.equal(
        await marker.getAttribute("data-callout"),
        String(index + 1),
      );
      assert.equal(
        await marker.locator("text").textContent(),
        String(index + 1),
      );
      const legend = page.locator(
        `#assembly-view ol li[data-piece-id="${entry.part_id}"]`,
      );
      assert.equal(await legend.getAttribute("value"), String(index + 1));
      assert.equal(
        await legend.textContent(),
        `${entry.display_name} · ${entry.reference}`,
      );
    }
    await page.locator("#assembly-stages button").first().click();
    for (const marker of await page
      .locator("#assembly-view svg g[data-piece-id]")
      .all()) {
      const id = await marker.getAttribute("data-piece-id");
      assert.equal(
        await marker.getAttribute("data-callout"),
        String(callouts.findIndex((p) => p.part_id === id) + 1),
      );
    }
    await page.locator("#construction-width").fill("210");
    const resized = await generate();
    assert.equal(
      resized.construction.piece_catalog.find(
        (p) => p.part_id === piece.part_id,
      ).reference,
      piece.reference,
    );
    for (const kind of ["polygon", "enclosure", "screen"]) {
      await page.locator("#construction-shape").selectOption(kind);
      assert.equal(await page.locator("#construction-sides").isVisible(), true);
      assert.equal(
        await page.locator("#construction-sides").isDisabled(),
        false,
      );
      await page.locator("#construction-sides").fill("5");
      const shape = await generate();
      assert.ok(shape.construction.steps.length);
      assert.equal(
        shape.construction.piece_catalog.length,
        kind === "polygon" ? 1 : 5,
      );
      assert.equal(
        shape.construction.request.target.assembly.parts.length,
        kind === "polygon" ? 1 : 5,
      );
      assert.equal(
        await page.locator("#construction-height").isDisabled(),
        kind === "polygon",
      );
      assert.ok(shape.fabrication_blockers.length);
    }
    if (fixture) {
      await page.locator("#construction-shape").selectOption("box");
      await page.locator("#construction-width").fill("200");
      await page.locator("#construction-depth").fill("300");
      await page
        .getByText("Import reviewed material and process records", {
          exact: true,
        })
        .click();
      async function importResources(value) {
        await page.locator("#materials-json").fill(JSON.stringify(value));
        await page.locator("#materials-import").click();
        assert.match(
          await page.locator("#materials-import-status").textContent(),
          /loaded as supplied data/,
        );
      }
      await importResources(fixture);
      const actual = await generate();
      assert.equal(actual.fabrication_basis, "supplied_materials_unverified");
      assert.equal(actual.fabrication_report.status, "ready");
      assert.equal(actual.fabrication_report.order_status, "complete");
      assert.deepEqual(
        actual.fabrication_plan.stocks,
        actual.request.resources.stocks,
      );
      assert.ok(
        actual.fabrication_report.operations.every(
          (op) => op.status !== "completed",
        ),
      );
      assert.match(
        await page.locator("#construction-fabrication").innerText(),
        /Supplied-material fabrication report/,
      );
      const shortage = structuredClone(fixture);
      shortage.stocks[0].usable_regions[0].geometry.width = 30;
      shortage.stocks[0].usable_regions[0].geometry.height = 30;
      await importResources(shortage);
      const blocked = await generate();
      assert.equal(blocked.fabrication_plan, null);
      assert.ok(blocked.fabrication_blockers.length);
      assert.equal(
        blocked.request.resources.stocks[0].usable_regions[0].geometry.width,
        30,
      );
      await page.locator("#construction-invented-stock").check();
      const synthetic = await generate();
      assert.equal(synthetic.fabrication_basis, "explicit_synthetic_fixture");
      assert.equal(synthetic.request.resources, undefined);
      await page.locator("#construction-invented-stock").uncheck();
      const restored = await generate();
      assert.equal(
        restored.request.resources.stocks[0].usable_regions[0].geometry.width,
        30,
      );
      assert.equal(restored.fabrication_plan, null);
    }
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    if (process.env.LAB_SCREENSHOT_DIR)
      await page.screenshot({
        path: `${process.env.LAB_SCREENSHOT_DIR}/materials-${width}.png`,
        fullPage: true,
      });
    console.log(
      `PASS ${width}px actual material entry/import, unknowns, stable names and escaping, expanded shapes, shortages, isolated synthetic mode`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
