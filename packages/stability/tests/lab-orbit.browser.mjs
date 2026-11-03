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
    let requests = 0;
    const errors = [];
    page.on("request", (r) => {
      if (r.url().endsWith("/inspect-plan")) requests++;
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.locator("#legacy-lab > summary").click();
    await page.waitForFunction(() => document.querySelector("#stand-view svg"));
    const read = async () =>
      JSON.parse(await page.locator("#stand-full-result").textContent());
    const frame = () =>
      page.evaluate(
        () =>
          new Promise((r) =>
            requestAnimationFrame(() => requestAnimationFrame(r)),
          ),
      );
    async function inspect(action) {
      const wait = page.waitForResponse(
        (r) =>
          r.url().endsWith("/inspect-plan") && r.request().method() === "POST",
      );
      await action();
      const response = await wait;
      assert.equal(response.status(), 200, await response.text());
      const result = await response.json();
      await page.waitForFunction(
        (expected) =>
          document.querySelector("#stand-full-result").textContent ===
          JSON.stringify(expected, null, 2),
        result,
      );
      return result;
    }
    await inspect(() => page.locator("#stand-stage").selectOption("6"));
    await page.locator("#stand-example").click();
    const baseline = await inspect(() => page.locator("#run-stand").click());
    assert.equal(baseline.report.status, "modeled_pass");
    const count = requests;
    const serialized = await page.locator("#stand-full-result").textContent();
    const viewport = page.locator("#stand-view");
    const polygons = () =>
      page
        .locator("#stand-view polygon")
        .evaluateAll((nodes) =>
          Object.fromEntries(
            nodes.map((n) => [n.dataset.facetId, n.getAttribute("points")]),
          ),
        );
    const initial = await polygons();
    const initialOrder = await page
      .locator("#stand-view polygon")
      .evaluateAll((nodes) => nodes.map((n) => n.dataset.facetId));
    await viewport.focus();
    for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowRight");
    await frame();
    assert.notDeepEqual(await polygons(), initial);
    assert.notDeepEqual(
      await page
        .locator("#stand-view polygon")
        .evaluateAll((nodes) => nodes.map((n) => n.dataset.facetId)),
      initialOrder,
    );
    for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowRight");
    await frame();
    assert.equal(await viewport.getAttribute("data-yaw"), "315");
    assert.deepEqual(await polygons(), initial);
    await page.keyboard.press("+");
    await frame();
    assert.ok(Number(await viewport.getAttribute("data-zoom")) > 1);
    await page.keyboard.press("Home");
    await frame();
    await viewport.scrollIntoViewIfNeeded();
    const box = await page.locator("#stand-view svg").boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height / 2, {
      steps: 8,
    });
    await page.mouse.up();
    await frame();
    assert.notEqual(await viewport.getAttribute("data-yaw"), "315");
    await page.locator("#stand-reset-camera").click();
    await viewport.scrollIntoViewIfNeeded();
    const touchBox = await page.locator("#stand-view svg").boundingBox();
    const session = await page.context().newCDPSession(page);
    const x = touchBox.x + touchBox.width * 0.4,
      y = touchBox.y + touchBox.height * 0.5;
    await session.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x, y, id: 1 }],
    });
    await session.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: x + 45, y, id: 1 }],
    });
    await session.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await frame();
    assert.notEqual(await viewport.getAttribute("data-yaw"), "315");
    await session.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [
        { x, y, id: 1 },
        { x: x + 40, y, id: 2 },
      ],
    });
    await session.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { x: x - 10, y, id: 1 },
        { x: x + 65, y, id: 2 },
      ],
    });
    await session.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await frame();
    assert.ok(Number(await viewport.getAttribute("data-zoom")) > 1);
    await page.locator("#stand-reset-camera").click();
    await frame();
    assert.equal(requests, count);
    assert.equal(
      await page.locator("#stand-full-result").textContent(),
      serialized,
    );
    const stage = await inspect(() =>
      page.locator("#stand-stage-example").click(),
    );
    assert.equal(stage.stage_analysis.reports.length, 3);
    assert.equal(await page.locator("#stand-result h3").count(), 3);
    assert.ok(stage.request.stage_snapshot);
    assert.match(
      await page.locator("#stand-geometry-caption").textContent(),
      /Explicit hypothetical/,
    );
    assert.equal(stage.report, null);
    await inspect(() => page.locator("#stand-stage").selectOption("6"));
    assert.equal(await page.locator("#stand-snapshot").inputValue(), "");
    await page.locator("#stand-example").click();
    for (const [kind, check] of [
      ["sliding", "slide"],
      ["joint", "joint"],
      ["beam", "deformation"],
    ]) {
      await page.locator(`[data-check-example=${kind}]`).click();
      const result = await inspect(() => page.locator("#run-stand").click());
      assert.ok(
        result.report.results.some(
          (r) => r.check_type === check && r.status === "modeled_pass",
        ),
        JSON.stringify(result.report.results),
      );
      assert.match(
        await page.locator("#stand-result").textContent(),
        new RegExp(check),
      );
    }
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    console.log(
      `PASS ${width}px: 360 keyboard, mouse/touch orbit, zoom/reset, camera leaves report/HTTP unchanged, three stage components, slide/joint/beam checks, no overflow/errors`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
