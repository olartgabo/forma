import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { chromium } = await import(pathToFileURL(process.argv[2]).href);
const base = process.argv[3] ?? "http://127.0.0.1:3031";
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname));
const browser = await chromium.launch({
  executablePath: process.env.LAB_BROWSER_PATH,
});
try {
  for (const width of [390, 1280]) {
    const page = await browser.newPage({
      viewport: { width, height: 1000 },
      hasTouch: true,
    });
    const errors = [];
    let analyses = 0;
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (r.url().endsWith("/evaluate-assembly")) analyses++;
    });
    await page.goto(base);
    await page
      .getByText("Examples, import and exact results", { exact: true })
      .click();
    await page
      .getByRole("button", { name: "Hypothetical polygon panels", exact: true })
      .click();
    await page
      .getByText("Examples, import and exact results", { exact: true })
      .click();
    await page.waitForSelector("#assembly-view polygon");
    const read = async () =>
      JSON.parse(await page.locator("#assembly-report").textContent());
    async function evaluate(
      action = () => page.locator("#assembly-evaluate").click(),
    ) {
      const wait = page.waitForResponse(
        (r) =>
          r.url().endsWith("/evaluate-assembly") &&
          r.request().method() === "POST",
      );
      await action();
      const response = await wait;
      assert.equal(response.status(), 200, await response.text());
      const result = await response.json();
      await page.waitForFunction(
        (expected) =>
          document.querySelector("#assembly-report").textContent ===
          JSON.stringify(expected, null, 2),
        result,
      );
      return result;
    }
    const initial = await read();
    assert.equal(initial.result.facets.length, 1);
    assert.equal(initial.result.facets[0].vertices.length, 3);
    assert.equal(initial.result.reports.length, 1);
    const next = await evaluate(() => page.locator("#assembly-next").click());
    assert.equal(next.result.facets.length, 2);
    assert.equal(next.result.reports.length, 2);
    assert.equal(next.result.future_part_ids.length, 1);
    const third = await evaluate(() => page.locator("#assembly-next").click());
    assert.equal(third.result.facets.length, 3);
    assert.equal(third.result.facets[2].vertices.length, 6);
    const baseline = await page.locator("#assembly-report").textContent();
    const count = analyses;
    await page.locator("#assembly-view").focus();
    for (let i = 0; i < 24; i++) await page.keyboard.press("ArrowRight");
    assert.equal(
      await page.locator("#assembly-view").getAttribute("data-yaw"),
      "315",
    );
    assert.equal(analyses, count);
    assert.equal(
      await page.locator("#assembly-report").textContent(),
      baseline,
    );
    await page.locator("#assembly-new").click();
    await page.locator("#assembly-add-panel").click();
    const unknown = await evaluate();
    assert.ok(unknown.result.reports.every((r) => r.status !== "modeled_pass"));
    const controls = page.locator("#assembly-panel-editor");
    await controls
      .getByLabel("Mass (g) — blank means unknown", { exact: true })
      .fill("40");
    await controls
      .getByLabel("Assume uniform sheet mass (centroid calculated by engine)", {
        exact: true,
      })
      .check();
    await controls
      .getByLabel("Assume this full face contacts the table", { exact: true })
      .check();
    await controls
      .getByLabel("Assume this panel behaves as a rigid body", { exact: true })
      .check();
    const known = await evaluate();
    assert.equal(known.result.reports[0].status, "modeled_pass");
    await controls
      .getByLabel("Polygon corners (x, y in mm; one corner per line)", {
        exact: true,
      })
      .fill("-50, -50\n50, -50\n0, 60");
    await controls
      .getByLabel("Polygon corners (x, y in mm; one corner per line)", {
        exact: true,
      })
      .blur();
    const triangle = await evaluate();
    assert.equal(triangle.result.facets[0].vertices.length, 3);
    await page.locator("#assembly-add-stage").click();
    assert.equal(await page.locator("#assembly-stages button").count(), 2);
    await page.locator("#assembly-add-panel").click();
    const added = await evaluate();
    assert.equal(added.result.facets.length, 2);
    assert.equal(added.result.reports.length, 2);
    const earlier = await evaluate(() =>
      page.locator("#assembly-prev").click(),
    );
    assert.equal(earlier.result.facets.length, 1);
    assert.equal(earlier.result.future_part_ids.length, 1);
    // Export must retain an unevaluated draft independently from the last result.
    await page.locator("#assembly-add-stage").click();
    await page.locator("#assembly-panel").selectOption("0");
    await controls
      .getByLabel("Mass (g) — blank means unknown", { exact: true })
      .fill("77");
    await controls
      .getByLabel("Mass (g) — blank means unknown", { exact: true })
      .blur();
    await page
      .getByText("Examples, import and exact results", { exact: true })
      .click();
    const downloadWaiting = page.waitForEvent("download");
    await page.locator("#assembly-export").click();
    const download = await downloadWaiting;
    const saved = JSON.parse(await readFile(await download.path(), "utf8"));
    assert.equal(saved.editor.panels[0].mass_g, 40);
    assert.equal(saved.draft_editor.panels[0].mass_g, 77);
    assert.equal(saved.draft_stage_index, 2);
    const beforeImport = analyses;
    await page
      .locator("#assembly-json")
      .fill(JSON.stringify({ ...saved, draft_stage_index: 999 }));
    await page.locator("#assembly-import").click();
    assert.match(
      await page.locator("#assembly-error").textContent(),
      /stage index/,
    );
    await page.locator("#assembly-json").fill(JSON.stringify(saved));
    await page.locator("#assembly-import").click();
    assert.equal(
      await controls
        .getByLabel("Mass (g) — blank means unknown", { exact: true })
        .inputValue(),
      "77",
    );
    assert.match(
      await page.locator("#assembly-step-count").textContent(),
      /STEP 3 \/ 3/,
    );
    assert.match(
      await page.locator("#assembly-status").textContent(),
      /Draft imported.*not current/,
    );
    assert.equal(await page.locator("#assembly-results details").count(), 0);
    assert.equal(await page.locator("#assembly-view polygon").count(), 0);
    assert.equal(analyses, beforeImport);
    const replayed = await evaluate();
    assert.equal(replayed.editor.panels[0].mass_g, 77);
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      "horizontal overflow",
    );
    assert.deepEqual(errors, []);
    assert.equal(await page.locator("#legacy-lab").getAttribute("open"), null);
    if (process.env.LAB_SCREENSHOT_DIR)
      await page.screenshot({
        path: `${process.env.LAB_SCREENSHOT_DIR}/assembly-${width}.png`,
        fullPage: true,
      });
    console.log(
      `PASS ${width}px: stage chips/navigation, triangle/square/hexagon, 360 camera-only, no-JSON new assembly, unknown then explicit mass/contact pass, polygon edit, future excluded, no overflow/errors`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
