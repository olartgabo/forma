// Synthetic browser transport only. No provider calls or physical-test claims.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [
  modulePath,
  baseUrl,
  output = "../output/material-board",
  constructionPath,
] = process.argv.slice(2);
if (!modulePath || !baseUrl)
  throw Error("Pass Playwright module and local URL");
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1"].includes(origin.hostname))
  throw Error("Local server required");
fs.mkdirSync(output, { recursive: true });
// Optional output of muse-construction-fixture.py supplies actual checked geometry.
const construction = constructionPath
  ? JSON.parse(fs.readFileSync(constructionPath, "utf8"))
  : null;
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
});
const categories = [
  "corrugated_cardboard",
  "duct_tape",
  null,
  "plastic_bottle",
  "felt",
  "string_twine",
  "paper_clips",
];
const names = [
  "Cardboard",
  "Duct tape",
  "Mystery object",
  "Bottle",
  "Felt",
  "Twine",
  "Clips",
];
const measurement = (unit) => ({
  value: null,
  unit,
  source: "unknown",
  confirmed: false,
});
try {
  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({
      viewport: { width, height: 1000 },
      serviceWorkers: "block",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const errors = [],
      mutations = [],
      external = [];
    let saved = categories.map((category, i) => ({
      id: `sample-${i}`,
      name: names[i],
      identity: category
        ? { outcome: "catalog", category_id: category }
        : { outcome: "uncertain" },
      identity_source: "muse_suggestion",
      visibility: "full",
      instance: "single",
      user_fields: [],
    }));
    let revision = "items-original";
    let releaseRead;
    let firstOpen = true;
    let failArt = true;
    let constructionMode = "success";
    let releaseConstruction;
    let constructionGate = new Promise((resolve) => {
      releaseConstruction = resolve;
    });
    const heldRead = new Promise((resolve) => {
      releaseRead = resolve;
    });
    const project = {
      id: "material-board-project",
      revision_id: "inventory-original",
      goal: "Make something from these materials",
      active_version_id: null,
      stocks: [],
      inventory_confirmed: false,
      requirements: {
        tools: ["Scissors", "Ruler"],
        device_description: null,
        constraints: {
          device_mass_g: measurement("g"),
          support_angle_deg: measurement("deg"),
          max_footprint_width_mm: measurement("mm"),
          max_footprint_height_mm: measurement("mm"),
          allowed_profile_ids: [],
          allow_purchases: false,
        },
      },
    };
    if (construction) {
      project.stocks = construction.project.stocks;
      project.inventory_confirmed = true;
    }
    const base = `/api/projects/${project.id}`;
    page.on("pageerror", (error) => errors.push(error.message));
    await context.route("**/*", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== origin.origin) {
        external.push(url.origin);
        return route.abort();
      }
      // Force representative art failure: labels and review links must survive.
      if (failArt && /cardboard.*\.(?:png|webp)$/i.test(url.pathname))
        return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === `${base}/measurement-decisions`)
        return route.fulfill({
          status: 503,
          json: {
            code: "unavailable",
            message:
              "Measurement decisions are outside this synthetic scenario",
          },
        });
      if (url.pathname === `${base}/construction/propose`) {
        assert.ok(construction);
        const body = request.postDataJSON();
        assert.equal(body.provider_context_consented, true);
        assert.equal(body.expected_revision_id, project.revision_id);
        await constructionGate;
        return constructionMode === "success"
          ? route.fulfill({
              json: {
                ...construction.result,
                project_id: project.id,
                inventory_revision_id: project.revision_id,
              },
            })
          : route.fulfill({
              status: 502,
              json: {
                code: "invalid_response",
                message: "Synthetic rejected proposal",
              },
            });
      }
      if (url.pathname === `${base}/recognized-items`) {
        if (request.method() === "GET") await heldRead;
        if (request.method() === "PUT") {
          const body = request.postDataJSON();
          assert.equal(body.expected_revision, revision);
          assert.ok(body.idempotency_key);
          mutations.push(body);
          saved = body.items;
          revision = "items-saved";
        } else assert.equal(request.method(), "GET");
        return route.fulfill({
          json: {
            project_id: project.id,
            revision,
            items: saved,
            problems: [],
          },
        });
      }
      if (request.method() !== "GET") {
        mutations.push({ unexpected: `${request.method()} ${url.pathname}` });
        return route.abort();
      }
      const responses = new Map([
        ["/api/provider/status", { configured: Boolean(construction) }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, project],
        [`${base}/media`, { media: [] }],
        [`${base}/plans`, { plans: [] }],
        [`${base}/photo-estimates`, { estimates: [] }],
      ]);
      return responses.has(url.pathname)
        ? route.fulfill({ json: responses.get(url.pathname) })
        : route.fulfill({
            status: 503,
            json: {
              code: "unavailable",
              message: "Outside this synthetic browser scenario",
            },
          });
    });
    async function open() {
      await page.goto(`${origin.origin}/?project=${project.id}`);
      await page
        .getByLabel("Owner credential")
        .fill("synthetic-material-board-owner");
      await page
        .getByRole("button", { name: "Open workbench", exact: true })
        .click();
      if (firstOpen) {
        await page
          .getByRole("region", { name: "Your materials so far", exact: true })
          .getByRole("status")
          .filter({ hasText: "Loading your saved materials" })
          .waitFor();
        releaseRead();
        firstOpen = false;
      }
      await page
        .getByRole("button", { name: "Review Cardboard", exact: true })
        .waitFor();
    }
    const board = page.getByRole("region", {
      name: "Your materials so far",
      exact: true,
    });
    const cutouts = board.locator("button[data-slot]");
    await open();
    await page.waitForFunction(
      (expected) =>
        document.querySelectorAll(
          '[aria-label="Your materials so far"] button[data-slot]',
        ).length === expected,
      width <= 600 ? 3 : 6,
    );
    assert.equal(await cutouts.count(), width <= 600 ? 3 : 6);
    await page.waitForFunction(
      () => !document.querySelector('[aria-label="Review Cardboard"] img'),
    );
    assert.match(
      await board
        .getByRole("button", { name: "Review Cardboard", exact: true })
        .innerText(),
      /\?/,
    );
    assert.equal(
      await board
        .getByRole("button", { name: "Review Mystery object", exact: true })
        .locator("img")
        .count(),
      0,
    );
    assert.match(await board.innerText(), /Representative pictures/);
    assert.equal(
      await page.locator("#material-review-details").getAttribute("open"),
      null,
    );
    const reviewTape = board.getByRole("button", {
      name: "Review Duct tape",
      exact: true,
    });
    if (width === 1280) {
      await reviewTape.focus();
      await reviewTape.press("Enter");
    } else await reviewTape.click();
    assert.notEqual(
      await page.locator("#material-review-details").getAttribute("open"),
      null,
    );
    assert.equal(await reviewTape.getAttribute("data-selected"), "true");
    assert.equal(
      await page.evaluate(() => document.activeElement?.closest("li")?.id),
      "item-sample-1",
    );
    const tape = page.locator("#item-sample-1");
    const previousArt = await board
      .getByRole("button", { name: "Review Duct tape", exact: true })
      .locator("img")
      .getAttribute("src");
    await tape.getByLabel(/What is it\?/).selectOption("masking_tape");
    await page.waitForFunction(
      (previous) =>
        document
          .querySelector('[aria-label="Review Duct tape"] img')
          ?.getAttribute("src") !== previous,
      previousArt,
    );
    await tape
      .getByLabel("Item name", { exact: true })
      .fill("Corrected masking tape");
    await tape.getByLabel("Item name", { exact: true }).press("Tab");
    await board
      .getByRole("button", {
        name: "Review Corrected masking tape",
        exact: true,
      })
      .waitFor();
    await page
      .getByRole("button", { name: "Save materials", exact: true })
      .click();
    await page.waitForFunction(
      () =>
        !document
          .querySelector('[aria-label="Your materials so far"] [role="status"]')
          ?.textContent.includes("Updating"),
    );
    assert.equal(mutations.length, 1, JSON.stringify(mutations));
    assert.equal(mutations[0].items[1].identity.category_id, "masking_tape");
    await open();
    await board
      .getByRole("button", {
        name: "Review Corrected masking tape",
        exact: true,
      })
      .waitFor();
    await board.scrollIntoViewIfNeeded();
    await board.screenshot({ path: path.join(output, `board-${width}.png`) });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
      false,
      `Page overflows at ${width}px`,
    );
    // Tools use saved requirements, and keep their existing edit destination.
    await board
      .getByRole("button", { name: /See all & edit materials/ })
      .click();
    for (let i = 2; i < 7; i++)
      await page
        .locator(`#item-sample-${i}`)
        .getByRole("button", { name: "Remove", exact: true })
        .click();
    await board
      .getByRole("button", { name: "Review Scissors", exact: true })
      .waitFor();
    await board
      .getByRole("button", { name: "Review Scissors", exact: true })
      .click();
    assert.equal(
      await page.evaluate(() => document.activeElement?.id),
      "available-tools",
    );
    assert.equal(
      await page.getByLabel("Available tools, one per line").inputValue(),
      "Scissors\nRuler",
    );
    failArt = false;
    page.on("dialog", (dialog) => dialog.accept());
    await open();
    await board
      .getByRole("button", { name: "Review Cardboard", exact: true })
      .locator("img")
      .waitFor();
    await page.waitForFunction(() =>
      [
        ...document.querySelectorAll(
          '[aria-label="Your materials so far"] img',
        ),
      ].every((img) => img.complete && img.naturalWidth > 0),
    );
    await board
      .locator("img")
      .evaluateAll((images) =>
        Promise.all(images.map((image) => image.decode())),
      );
    await board.screenshot({
      path: path.join(output, `board-normal-${width}.png`),
    });
    if (construction) {
      const panel = page.getByRole("region", {
        name: "Invent with my materials",
        exact: true,
      });
      const ask = panel.getByRole("button", {
        name: "Ask MetaMuse for shapes and steps",
        exact: true,
      });
      await panel.getByLabel(/Send the saved goal/).check();
      await ask.click();
      await board
        .getByRole("status")
        .filter({ hasText: "Preparing your design" })
        .waitFor();
      await page.waitForFunction(() => {
        const bounds = document
          .querySelector('[aria-label="Your materials so far"]')
          ?.getBoundingClientRect();
        return bounds && bounds.top >= -1 && bounds.top < innerHeight;
      });
      assert.equal(
        await cutouts.count(),
        width <= 600 ? 3 : 6,
        "board remains populated while pending",
      );
      assert.equal(
        await board.getByRole("button", { name: /View your design/ }).count(),
        0,
      );
      await board.screenshot({
        path: path.join(output, `board-pending-${width}.png`),
      });
      releaseConstruction();
      const view = board.getByRole("button", { name: /View your design/ });
      await view.waitFor();
      await view.click();
      await panel
        .getByRole("heading", { name: "Proposed organizer", exact: true })
        .waitFor();
      assert.equal(
        await page.evaluate(() =>
          document.activeElement
            ?.closest("section")
            ?.getAttribute("aria-labelledby"),
        ),
        "muse-construction-title",
      );
      await panel
        .getByRole("button", { name: "Start another proposal", exact: true })
        .click();
      constructionMode = "failure";
      constructionGate = new Promise((resolve) => {
        releaseConstruction = resolve;
      });
      await panel.getByLabel(/Send the saved goal/).check();
      await ask.click();
      await board
        .getByRole("status")
        .filter({ hasText: "Preparing your design" })
        .waitFor();
      releaseConstruction();
      await panel.getByText(/server rejected the model output/).waitFor();
      assert.equal(
        await board.getByRole("button", { name: /View your design/ }).count(),
        0,
        "failed request cannot expose success navigation",
      );
      assert.equal(await cutouts.count(), width <= 600 ? 3 : 6);
    }
    // Reference-like composition still comes from normal recognized records and tools.
    saved = [
      { ...saved[0] },
      {
        ...saved[1],
        name: "Duct tape",
        identity: { outcome: "catalog", category_id: "duct_tape" },
      },
    ];
    project.requirements.tools = ["Scissors", "Utility knife"];
    await open();
    await board
      .getByRole("button", { name: "Review Duct tape", exact: true })
      .waitFor();
    await page.waitForFunction(() =>
      [
        ...document.querySelectorAll(
          '[aria-label="Your materials so far"] img',
        ),
      ].every((img) => img.complete && img.naturalWidth > 0),
    );
    await board
      .locator("img")
      .evaluateAll((images) =>
        Promise.all(images.map((image) => image.decode())),
      );
    await board.screenshot({
      path: path.join(output, `board-reference-${width}.png`),
    });
    const fan = await cutouts.evaluateAll((buttons) =>
      buttons.map((button) =>
        parseFloat(button.style.getPropertyValue("--tilt")),
      ),
    );
    assert.ok(fan[0] < 0 && fan.at(-1) > 0, "outer objects lean outwards");
    const hoverTarget = board.getByRole("button", {
      name: "Review Duct tape",
      exact: true,
    });
    await hoverTarget.hover();
    const hoverStyle = await hoverTarget.locator("img").evaluate((img) => ({
      filter: getComputedStyle(img).filter,
      scale: getComputedStyle(img).getPropertyValue("--scale"),
    }));
    assert.match(hoverStyle.filter, /rgba\(255, 255, 255, 0\.28\) 0px 0px 8px/);
    assert.doesNotMatch(hoverStyle.filter, /rgb\(255, 255, 255\) 2px/);
    assert.equal(hoverStyle.scale.trim(), "1.06");
    assert.equal(
      await cutouts.locator("svg path").count(),
      await cutouts.count(),
    );
    assert.equal(
      await cutouts.locator("svg circle").count(),
      await cutouts.count(),
    );
    const annotations = await cutouts.evaluateAll((buttons) =>
      buttons.map((button) => {
        const label = button.querySelector("span:last-child");
        const style = getComputedStyle(label);
        const rect = label.getBoundingClientRect();
        const board = button.closest("section").getBoundingClientRect();
        return {
          background: style.backgroundColor,
          italic: style.fontStyle,
          inside: rect.left >= board.left && rect.right <= board.right,
          rect: {
            left: rect.left,
            right: rect.right,
            top: rect.top,
            bottom: rect.bottom,
          },
        };
      }),
    );
    for (const annotation of annotations) {
      assert.equal(annotation.background, "rgba(0, 0, 0, 0)");
      assert.equal(annotation.italic, "italic");
      assert.ok(annotation.inside, `Annotation cropped at ${width}px`);
    }
    for (let i = 1; i < annotations.length; i++) {
      const a = annotations[i - 1].rect,
        b = annotations[i].rect;
      assert.ok(
        a.right <= b.left || a.bottom <= b.top || b.bottom <= a.top,
        `Annotations overlap at ${width}px`,
      );
    }
    await board.screenshot({
      path: path.join(output, `board-hover-${width}.png`),
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.equal(
      mutations.some((m) => m.unexpected),
      false,
    );
    console.log(
      `PASS material board ${width}px: cap, uncertain fallback, edit focus, correction, save/reload, tools, overflow`,
    );
    await context.close();
  }
} finally {
  await browser.close();
}
