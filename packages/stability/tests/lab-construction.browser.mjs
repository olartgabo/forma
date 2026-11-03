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
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    let generations = 0;
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (r.url().endsWith("/generate-construction")) generations++;
    });
    await page.goto(base);
    assert.equal(
      await page.locator("#construction-invented-stock").isChecked(),
      false,
    );
    assert.equal(
      await page.locator("#construction-custom").getAttribute("open"),
      null,
    );
    async function generate() {
      const wait = page.waitForResponse((r) =>
        r.url().endsWith("/generate-construction"),
      );
      await page.locator("#construction-generate").click();
      const response = await wait;
      assert.equal(response.status(), 200, await response.text());
      const payload = await response.json();
      await page.waitForFunction(() =>
        document
          .querySelector("#construction-status")
          .textContent.includes("steps generated"),
      );
      return payload;
    }
    const box = await generate();
    assert.ok(box.construction.steps.length > 3);
    assert.equal(box.fabrication_report, null);
    assert.match(
      await page.locator("#construction-fabrication").textContent(),
      /No fabrication approval/,
    );
    assert.equal(
      await page.locator("#assembly-stages button").count(),
      box.construction.steps.length,
    );
    const count = generations;
    await page.locator("#assembly-next").click();
    assert.match(
      await page.locator("#construction-instruction").textContent(),
      /not been performed/,
    );
    assert.equal(generations, count);
    await page.locator("#assembly-view").focus();
    for (let i = 0; i < 24; i++) await page.keyboard.press("ArrowRight");
    assert.equal(
      await page.locator("#assembly-view").getAttribute("data-yaw"),
      "315",
    );
    assert.equal(generations, count);
    await page.locator("#construction-width").fill("260");
    await page.locator("#construction-width").blur();
    assert.match(
      await page.locator("#construction-status").textContent(),
      /changed/,
    );
    await page.locator("#construction-invented-stock").check();
    const scaled = await generate();
    assert.notEqual(
      scaled.construction.target_hash,
      box.construction.target_hash,
    );
    assert.ok(scaled.fabrication_report);
    assert.doesNotMatch(
      await page.locator("#assembly-workspace").innerText(),
      /fab-[a-f0-9]+-/,
    );
    assert.match(
      await page.locator("#assembly-step-title").textContent(),
      /^Place /,
    );
    assert.ok(scaled.construction.steps.some((s) => s.operation_ids.length));
    assert.ok(
      scaled.fabrication_report.operations.every(
        (op) => op.status !== "completed",
      ),
    );
    assert.match(
      await page.locator("#construction-fabrication").textContent(),
      /Hypothetical fabrication report/,
    );
    for (const kind of ["ramp", "triangle", "concave"]) {
      await page.locator("#construction-shape").selectOption(kind);
      assert.equal(
        await page.locator("#construction-height").isDisabled(),
        ["triangle", "concave"].includes(kind),
      );
      const shape = await generate();
      if (kind === "triangle") {
        await page.locator("#construction-depth").fill("190");
        const resized = await generate();
        assert.notEqual(
          resized.construction.target_hash,
          shape.construction.target_hash,
        );
        assert.notDeepEqual(
          resized.construction.steps[0].analysis.facets,
          shape.construction.steps[0].analysis.facets,
        );
      }
      assert.ok(shape.construction.steps.length > 0);
      if (kind === "triangle" || kind === "concave")
        assert.ok(
          shape.fabrication_blockers.length > 0 ||
            shape.fabrication_report?.status === "blocked",
        );
    }
    await page.locator("#construction-shape").selectOption("box");
    const finalBox = await generate();
    assert.ok(finalBox.fabrication_instructions.length > 0);
    assert.match(
      await page.locator("#construction-fabrication").textContent(),
      /Cut.*panels/,
    );
    await page.locator("#assembly-stages button").last().click();
    assert.equal(
      await page.locator("#assembly-view polygon").count(),
      finalBox.construction.steps.at(-1).analysis.facets.length,
    );
    assert.equal(
      await page.locator("#assembly-step-title").textContent(),
      "Inspect assembly",
    );
    assert.match(
      await page.locator("#construction-fabrication").innerText(),
      /Waiting for \d+ earlier operations/,
    );
    assert.doesNotMatch(
      await page.locator("#assembly-workspace").innerText(),
      /fab-[a-f0-9]+-/,
    );
    assert.match(
      await page.locator("#construction-fabrication details pre").textContent(),
      /fab-[a-f0-9]+-/,
    );
    await page
      .getByText("Examples, import and exact results", { exact: true })
      .click();
    const downloading = page.waitForEvent("download");
    await page.locator("#assembly-export").click();
    const download = await downloading;
    assert.equal(
      download.suggestedFilename(),
      "forma-construction-experiment.json",
    );
    const saved = JSON.parse(await readFile(await download.path(), "utf8"));
    assert.deepEqual(saved.request.shape, finalBox.request.shape);
    assert.equal(
      saved.construction.steps.length,
      finalBox.construction.steps.length,
    );
    assert.equal(
      saved.selected_step_index,
      finalBox.construction.steps.length - 1,
    );
    if (process.env.LAB_DOWNLOAD_DIR)
      await download.saveAs(
        `${process.env.LAB_DOWNLOAD_DIR}/construction-feedback-${width}.json`,
      );
    const beforeImport = generations;
    await page.locator("#assembly-json").fill(JSON.stringify(saved));
    await page.locator("#assembly-import").click();
    assert.match(
      await page.locator("#assembly-error").textContent(),
      /manual editor drafts only/,
    );
    assert.equal(generations, beforeImport);
    await page
      .getByText("Examples, import and exact results", { exact: true })
      .click();
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    if (process.env.LAB_SCREENSHOT_DIR)
      await page.screenshot({
        path: `${process.env.LAB_SCREENSHOT_DIR}/construction-${width}.png`,
        fullPage: true,
      });
    console.log(
      `PASS ${width}px automatic target generation, dimension-sensitive hash, server stage navigation, camera-only, opt-in mapped fabrication, four shape targets, no completion/no errors`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
