// Synthetic UI replay only: no provider, persisted physical evidence or live API.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";

const [modulePath, baseUrl, outputDir, previewFixturePath] =
  process.argv.slice(2);
if (outputDir) await mkdir(outputDir, { recursive: true });
if (!modulePath || !baseUrl || !previewFixturePath)
  throw new Error(
    "Usage: node workshop-dashboard.browser.mjs <Playwright module> <local web URL> <output dir> <native preview fixtures JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("A local server is required.");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);
const credential = "synthetic-dashboard-owner";
const previewFixtures = JSON.parse(await readFile(previewFixturePath, "utf8"));
const fixture = {
  id: "synthetic-dashboard-project",
  goal: "Desk organizer",
  revision_id: "synthetic-revision",
  stocks: [
    {
      id: "synthetic-stock",
      kind: "sheet",
      material: "cardboard",
      condition: "uncertain",
      ...Object.fromEntries(
        ["width_mm", "height_mm", "thickness_mm", "remaining_length_mm"].map(
          (key) => [
            key,
            { value: null, unit: "mm", source: "unknown", confirmed: false },
          ],
        ),
      ),
      usable_regions: [],
      image_ids: [],
    },
  ],
  inventory_confirmed: false,
  active_version_id: null,
};
const summaries = [
  fixture,
  {
    ...fixture,
    id: `${fixture.id}-b`,
    goal: "Cable organizer",
    inventory_confirmed: true,
  },
  {
    ...fixture,
    id: `${fixture.id}-c`,
    goal: "Phone stand",
    inventory_confirmed: true,
    active_version_id: "synthetic-plan",
  },
];

const capture = (page, options = {}) =>
  page.screenshot({
    fullPage: true,
    // Development tooling floats over the sidebar corner; it is absent in production.
    style: "nextjs-portal { visibility: hidden !important; }",
    ...options,
  });

// Check the rendered stroke, not just CSS declarations: clipping a rectangular
// border used to remove all four diagonal corner segments.
async function assertClosedBlueprintBorders(page) {
  const text = await page.locator("main").innerText();
  assert(
    !/your personal workshop|concept preview|ordered by project id|first in project id order|project id order|more available|make\. adapt\. repeat\.|turn what you have into what you need|designed to be reimagined/i.test(
      text,
    ),
    "removed captions and slogans stay absent",
  );
  await page.evaluate(() => document.fonts.ready);
  assert(
    await page.evaluate(() => document.fonts.check('500 16px "Forma Manrope"')),
    "the bundled workshop font loaded",
  );
  const surfaces = await page
    .locator("[data-blueprint-surface]")
    .evaluateAll((elements) =>
      elements.flatMap((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const cut = parseFloat(style.getPropertyValue("--panel-cut"));
        if (!rect.width || !rect.height || !Number.isFinite(cut) || cut < 4)
          return [];
        return [
          {
            name: element.getAttribute("data-blueprint-surface"),
            x: rect.x + scrollX,
            y: rect.y + scrollY,
            width: rect.width,
            height: rect.height,
            cut,
          },
        ];
      }),
    );
  assert(surfaces.length > 0, "the dashboard has visible outlined panels");
  const screenshot = await capture(page);
  const missing = await page.evaluate(
    async ({ png, surfaces }) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0);
      const missing = [];
      for (const surface of surfaces) {
        for (const [corner, right, bottom] of [
          ["top-left", false, false],
          ["top-right", true, false],
          ["bottom-right", true, true],
          ["bottom-left", false, true],
        ]) {
          for (const t of [0.25, 0.5, 0.75]) {
            const dx = surface.cut * t + 0.7;
            const dy = surface.cut * (1 - t) + 0.7;
            const x = Math.round(surface.x + (right ? surface.width - dx : dx));
            const y = Math.round(
              surface.y + (bottom ? surface.height - dy : dy),
            );
            const pixels = context.getImageData(x - 1, y - 1, 3, 3).data;
            let white = false;
            for (let i = 0; i < pixels.length; i += 4) {
              const channels = [pixels[i], pixels[i + 1], pixels[i + 2]];
              if (
                Math.min(...channels) > 205 &&
                Math.max(...channels) - Math.min(...channels) < 45
              )
                white = true;
            }
            if (!white) missing.push(`${surface.name} ${corner} ${t}`);
          }
        }
      }
      return missing;
    },
    { png: screenshot.toString("base64"), surfaces },
  );
  if (missing.length && outputDir)
    await capture(page, { path: path.join(outputDir, "border-failure.png") });
  assert.deepEqual(
    missing,
    [],
    "all clipped corners have a continuous visible outline",
  );
}

async function scenario(width, mode, savedDrawing = false) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    serviceWorkers: "block",
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [],
    unexpected = [],
    writes = [];
  let listCalls = 0;
  let moreCalls = 0;
  let researchPosts = 0;
  let researchReads = 0;
  let latestResearch;
  let finishResearch;
  const researchGate = new Promise((resolve) => {
    finishResearch = resolve;
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin.origin) {
      unexpected.push(`external ${url.hostname}`);
      return route.abort("blockedbyclient");
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    assert.equal(request.headers().authorization, `Bearer ${credential}`);
    if (
      request.method() === "POST" &&
      url.pathname === `/api/projects/${fixture.id}/sourcing/research`
    ) {
      researchPosts++;
      const body = request.postDataJSON();
      assert.equal(body.source, "supplier_page");
      await researchGate;
      latestResearch = {
        id: "retained-research",
        project_id: fixture.id,
        revision_id: fixture.revision_id,
        item: body.item,
        area: body.area,
        currency: body.currency,
        observed_at: "2026-11-04T12:00:00Z",
        status: researchPosts === 1 ? "succeeded" : "outcome_unknown",
        offers: [],
        usage: null,
        error: researchPosts === 1 ? null : "provider_outcome_unknown",
        replayed: false,
      };
      return route.fulfill({ json: latestResearch });
    }
    if (request.method() !== "GET") {
      writes.push(`${request.method()} ${url.pathname}`);
      return route.abort("blockedbyclient");
    }
    if (url.pathname === "/api/provider/status")
      return route.fulfill({ json: { configured: false } });
    if (url.pathname === "/api/projects") {
      listCalls++;
      // Real pending response makes the loading state observable.
      await new Promise((resolve) => setTimeout(resolve, 250));
      if (mode === "error")
        return route.fulfill({ status: 503, json: { code: "unavailable" } });
      if (url.searchParams.has("cursor")) {
        moreCalls++;
        if (moreCalls === 1)
          return route.fulfill({ status: 503, json: { code: "unavailable" } });
        return route.fulfill({
          json: {
            projects: [
              {
                ...fixture,
                id: `${fixture.id}-d`,
                goal: "Tool caddy",
              },
            ],
            next_cursor: null,
          },
        });
      }
      return route.fulfill({
        json: {
          projects: mode === "populated" ? summaries : [],
          next_cursor: mode === "populated" ? summaries[2].id : null,
        },
      });
    }
    const base = `/api/projects/${fixture.id}`;
    if (url.pathname === `${base}/sourcing/research/retained-research`) {
      researchReads++;
      return route.fulfill({
        json: { ...latestResearch, status: "succeeded", error: null },
      });
    }
    const selected = summaries.find((project) =>
      url.pathname.startsWith(`/api/projects/${project.id}/`),
    );
    if (url.pathname.endsWith("/construction/preview")) {
      if (!selected)
        return route.fulfill({ status: 404, json: { code: "not_found" } });
      assert.equal(
        url.searchParams.get("expected_inventory_revision_id"),
        selected.revision_id,
      );
      const native =
        selected.id === summaries[0].id
          ? previewFixtures.generic_one
          : previewFixtures.generic_two;
      return route.fulfill({
        json: {
          ...native,
          project_id: selected.id,
          inventory_revision_id: selected.revision_id,
        },
      });
    }
    if (url.pathname.endsWith("/geometry")) {
      assert(selected);
      assert.equal(
        url.searchParams.get("expected_inventory_revision_id"),
        selected.revision_id,
      );
      if (savedDrawing)
        return route.fulfill({
          status: 422,
          json: { code: "validation_error" },
        });
      return route.fulfill({
        json: {
          ...previewFixtures.legacy,
          project_id: selected.id,
          plan_version_id: selected.active_version_id,
        },
      });
    }
    if (
      selected?.active_version_id &&
      url.pathname.endsWith(`/versions/${selected.active_version_id}`)
    ) {
      const version = previewFixtures.legacy_version;
      return route.fulfill({
        json: {
          ...version,
          project_id: selected.id,
          version_id: selected.active_version_id,
          inventory_revision_id: selected.revision_id,
          plan: {
            ...version.plan,
            project_id: selected.id,
            version_id: selected.active_version_id,
          },
          manual: {
            ...version.manual,
            project_id: selected.id,
            version_id: selected.active_version_id,
          },
        },
      });
    }
    if (url.pathname === base) return route.fulfill({ json: fixture });
    if (url.pathname === `${base}/media`)
      return route.fulfill({ json: { media: [] } });
    if (url.pathname === `${base}/sourcing/needs`)
      return route.fulfill({
        json: {
          project_id: fixture.id,
          revision_id: fixture.revision_id,
          active_version_id: null,
          needs: [],
          guidance: [],
          marketplace_status: "authorization_required",
          pending_run_id: null,
        },
      });
    if (url.pathname === `${base}/recognized-items`)
      return route.fulfill({
        json: {
          project_id: fixture.id,
          revision: "items-a",
          items: [],
          problems: [],
        },
      });
    if (url.pathname === `${base}/photo-estimates`)
      return route.fulfill({ json: { records: [] } });
    if (url.pathname === `${base}/synthesis/research`)
      return route.fulfill({ json: { enabled: false } });
    if (url.pathname === `${base}/plans`)
      return route.fulfill({ json: { plans: [] } });
    if (/^\/api\/projects\/[^/]+\/plans$/.test(url.pathname))
      return route.fulfill({ json: { plans: [] } });
    if (url.pathname === `${base}/designs/readiness`)
      return route.fulfill({ status: 503, json: { code: "unavailable" } });
    unexpected.push(url.pathname);
    return route.abort("blockedbyclient");
  });
  try {
    await page.goto(baseUrl);
    await page.getByLabel("Owner credential", { exact: true }).fill(credential);
    await page
      .getByRole("button", { name: "Open workbench", exact: true })
      .click();
    await page.getByText(/loading.*projects/i).waitFor();
    if (mode === "error") {
      await page.getByRole("alert").first().waitFor();
      await assertClosedBlueprintBorders(page);
      assert.equal(
        await page
          .getByRole("heading", { name: "Your workshop starts here." })
          .count(),
        0,
        "failed load is not a successful empty list",
      );
    } else if (mode === "populated") {
      await page
        .getByRole("button", { name: /Resume a saved project/ })
        .waitFor();
      await page
        .locator(
          '[data-blueprint-surface="resume-hero"] [data-engine-model="ready"]',
        )
        .waitFor();
      await assertClosedBlueprintBorders(page);
      if (outputDir)
        await capture(page, {
          path: path.join(
            outputDir,
            `synthetic-home-${width}${savedDrawing ? "-saved-drawing" : ""}.png`,
          ),
          fullPage: true,
        });
      const nav = page.getByRole("navigation", {
        name: "Workshop",
        exact: true,
      });
      await nav
        .getByRole("button", { name: "My projects", exact: true })
        .click();
      // Each shape comes from a persisted engine response, including new designs
      // that have no prepared artwork. Wait for lazy captures before screenshots.
      const cards = page.locator(
        "article[data-blueprint-surface='project-card']",
      );
      for (const [index, card] of (await cards.all()).entries()) {
        await card.scrollIntoViewIfNeeded();
        if (savedDrawing && index === 2) {
          const image = card.getByRole("img", {
            name: "Saved engine assembly drawing",
          });
          await image.waitFor();
          await image.evaluate((image) => image.decode());
          const drawing = await image.evaluate((image) =>
            fetch(image.src).then((response) => response.text()),
          );
          assert(
            !/<(?:text|title|desc)\b/i.test(drawing),
            "saved drawing capture contains geometry, not manual text",
          );
        } else await card.locator('[data-engine-model="ready"]').waitFor();
      }
      await page.evaluate(() => scrollTo(0, 0));
      const nativeModels = await cards
        .locator('[data-engine-model="ready"]')
        .evaluateAll((models) =>
          models.map((model) =>
            [
              ...model.querySelectorAll(
                "[data-engine-facet] > polygon:first-child",
              ),
            ]
              .map((face) => face.getAttribute("points"))
              .join("|"),
          ),
        );
      assert.equal(
        new Set(nativeModels).size,
        savedDrawing ? 2 : 3,
        "three engine geometries produce distinct previews independent of project names",
      );
      const svgIds = await page
        .locator("svg [id]")
        .evaluateAll((nodes) => nodes.map((node) => node.id));
      assert.equal(
        new Set(svgIds).size,
        svgIds.length,
        "each model has independent material IDs",
      );
      assert.equal(
        await cards.locator("ellipse, filter").count(),
        0,
        "project captures contain no floor or drop shadows",
      );
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        "project catalog fits viewport",
      );
      await assertClosedBlueprintBorders(page);
      if (outputDir)
        await capture(page, {
          path: path.join(
            outputDir,
            `synthetic-projects-${width}${savedDrawing ? "-saved-drawing" : ""}.png`,
          ),
          fullPage: true,
        });
      await page.getByLabel("Search projects").fill("cable organizer");
      assert.equal(
        await page
          .getByRole("button", { name: "Open project", exact: true })
          .count(),
        1,
      );
      await page.getByLabel("Search projects").fill("");
      await page.getByRole("button", { name: /^Filters/ }).click();
      await assertClosedBlueprintBorders(page);
      await page
        .getByRole("radio", { name: "Active plan", exact: true })
        .check();
      assert.equal(
        await page
          .getByRole("button", { name: "Open project", exact: true })
          .count(),
        1,
      );
      await page
        .getByRole("radio", { name: "All projects", exact: true })
        .check();
      await page
        .getByRole("button", {
          name: `Add ${fixture.goal} to favorites`,
          exact: true,
        })
        .click();
      await page.getByRole("radio", { name: "Favorites", exact: true }).check();
      assert.equal(
        await page
          .getByRole("button", { name: "Open project", exact: true })
          .count(),
        1,
      );
      await page
        .getByRole("radio", { name: "All projects", exact: true })
        .check();
      if (width > 760) {
        await page
          .getByRole("button", { name: "List view", exact: true })
          .click();
        assert.equal(
          await page
            .getByRole("button", { name: "List view", exact: true })
            .getAttribute("aria-pressed"),
          "true",
        );
        for (const resizedWidth of [390, 320]) {
          await page.setViewportSize({ width: resizedWidth, height: 844 });
          const geometry = await page
            .getByRole("button", { name: "Open project", exact: true })
            .evaluateAll((buttons) => ({
              fitsDocument:
                document.documentElement.scrollWidth <= innerWidth + 1,
              buttons: buttons.map((button) => {
                const bounds = button.getBoundingClientRect();
                const card = button.closest("article").getBoundingClientRect();
                return {
                  left: bounds.left,
                  right: bounds.right,
                  cardLeft: card.left,
                  cardRight: card.right,
                  viewportWidth: innerWidth,
                };
              }),
            }));
          assert(
            geometry.fitsDocument,
            `retained List view fits ${resizedWidth}px document`,
          );
          assert(geometry.buttons.length > 0);
          for (const button of geometry.buttons) {
            assert(
              button.left >= Math.max(0, button.cardLeft) - 1 &&
                button.right <=
                  Math.min(button.viewportWidth, button.cardRight) + 1,
              `retained List view action fits card and viewport at ${resizedWidth}px: ${JSON.stringify(button)}`,
            );
          }
        }
        await page.setViewportSize({ width, height: 844 });
        await page
          .getByRole("button", { name: "Grid view", exact: true })
          .click();
      }
      await page.getByRole("button", { name: /Load more projects/ }).click();
      await page.getByRole("alert").waitFor();
      assert.equal(
        await page
          .getByRole("button", { name: "Open project", exact: true })
          .count(),
        3,
      );
      await page
        .getByRole("button", { name: "Try again", exact: true })
        .click();
      await page.getByRole("heading", { name: "Tool caddy" }).waitFor();
      assert.equal(
        await page
          .getByRole("button", { name: "Open project", exact: true })
          .count(),
        4,
      );
      for (const section of ["Shopping list", "Explore"]) {
        await nav.getByRole("button", { name: section, exact: true }).click();
        await assertClosedBlueprintBorders(page);
      }
      if (width === 1280 && !savedDrawing) {
        await nav
          .getByRole("button", { name: "Shopping list", exact: true })
          .click();
        await page.getByLabel("Shopping project").selectOption(fixture.id);
        await page.getByLabel("Research method").selectOption("supplier_page");
        await page
          .getByLabel("Supplier product URL")
          .fill("https://supplier.example/scissors");
        await page
          .getByLabel("City and country", { exact: true })
          .fill("La Paz, Bolivia");
        await page.getByLabel("Item to research").fill("one pair of scissors");
        await page.getByLabel("Price currency", { exact: true }).fill("BOB");
        await nav.getByRole("button", { name: "Home", exact: true }).click();
        await nav
          .getByRole("button", { name: "Shopping list", exact: true })
          .click();
        assert.equal(
          await page.getByLabel("Shopping project").inputValue(),
          fixture.id,
        );
        assert.equal(
          await page.getByLabel("Item to research").inputValue(),
          "one pair of scissors",
        );
        assert.equal(
          await page.getByLabel("Supplier product URL").inputValue(),
          "https://supplier.example/scissors",
        );
        await page
          .getByRole("button", { name: "Check supplier page", exact: true })
          .click();
        assert(await page.getByLabel("Shopping project").isDisabled());
        assert(
          await nav
            .getByRole("button", { name: "Home", exact: true })
            .isDisabled(),
        );
        assert(
          await page
            .getByRole("button", { name: /New project/ })
            .first()
            .isDisabled(),
        );
        finishResearch();
        await page
          .getByRole("button", { name: "Check supplier page", exact: true })
          .waitFor();
        await nav.getByRole("button", { name: "Home", exact: true }).click();
        await nav
          .getByRole("button", { name: "Shopping list", exact: true })
          .click();
        assert.equal(
          await page.getByLabel("Shopping project").inputValue(),
          fixture.id,
        );
        assert.equal(
          await page.getByLabel("Item to research").inputValue(),
          "one pair of scissors",
        );
        assert.equal(researchPosts, 1);
        await page
          .getByRole("button", { name: "Check supplier page", exact: true })
          .click();
        await page
          .getByText("The previous research outcome is unresolved.", {
            exact: false,
          })
          .waitFor();
        assert(await page.getByLabel("Shopping project").isDisabled());
        assert.equal(
          await nav
            .getByRole("button", { name: "Home", exact: true })
            .isDisabled(),
          false,
        );
        await nav.getByRole("button", { name: "Home", exact: true }).click();
        await nav
          .getByRole("button", { name: "Shopping list", exact: true })
          .click();
        assert.equal(
          await page.getByLabel("Item to research").inputValue(),
          "one pair of scissors",
        );
        assert(await page.getByLabel("Shopping project").isDisabled());
        await page
          .getByRole("button", { name: "Check research status", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Check supplier page", exact: true })
          .waitFor();
        assert.equal(
          await page.getByLabel("Shopping project").isDisabled(),
          false,
        );
        assert.equal(researchPosts, 2);
        assert.equal(researchReads, 1);
      }
      await nav
        .getByRole("button", { name: "My materials", exact: true })
        .click();
      await page.getByText("synthetic-stock", { exact: true }).waitFor();
      await assertClosedBlueprintBorders(page);
      await page
        .getByRole("button", { name: /Open project materials/ })
        .click();
      await page
        .getByRole("heading", { name: fixture.goal, exact: true })
        .waitFor();
      assert.equal(new URL(page.url()).searchParams.get("project"), fixture.id);
      await page
        .getByRole("button", { name: "Back to workshop", exact: true })
        .click();
      assert.equal(new URL(page.url()).searchParams.get("project"), null);
      await page
        .getByRole("button", {
          name: `Remove ${fixture.goal} from favorites`,
          exact: true,
        })
        .waitFor();
      await page
        .getByRole("button", { name: /^Return to current project/ })
        .click();
      assert.equal(new URL(page.url()).searchParams.get("project"), fixture.id);
      await page
        .getByRole("button", { name: "Back to workshop", exact: true })
        .click();
    } else {
      await page
        .getByRole("heading", { name: "Your workshop starts here." })
        .waitFor();
      await assertClosedBlueprintBorders(page);
      if (outputDir)
        await capture(page, {
          path: path.join(outputDir, `synthetic-empty-${width}.png`),
          fullPage: true,
        });
      await page
        .getByRole("button", { name: /new project/i })
        .first()
        .click();
      await page
        .getByLabel("Your goal, in English or Spanish")
        .fill("SYNTHETIC unsaved goal");
      page.once("dialog", (dialog) => dialog.accept());
      await page
        .getByRole("button", { name: "Back to workshop", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Your workshop starts here." })
        .waitFor();
      await page
        .getByRole("button", { name: /^Return to unsaved draft/ })
        .click();
      assert.equal(
        await page.getByLabel("Your goal, in English or Spanish").inputValue(),
        "SYNTHETIC unsaved goal",
      );
      page.once("dialog", (dialog) => dialog.accept());
      await page
        .getByRole("button", { name: "Back to workshop", exact: true })
        .click();
    }
    assert.equal(await page.locator("main").count(), 1);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      "dashboard fits viewport",
    );
    assert.equal(
      await page.evaluate(
        () =>
          JSON.stringify(localStorage).includes("synthetic-dashboard-owner") ||
          JSON.stringify(sessionStorage).includes("synthetic-dashboard-owner"),
      ),
      false,
    );
    assert(listCalls > 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    assert.deepEqual(writes, []);
    console.log(
      `PASS dashboard ${mode} ${width}px: intercepted software replay, zero writes/provider calls`,
    );
  } finally {
    await context.close();
  }
}
try {
  await scenario(1280, "empty");
  await scenario(1280, "error");
  await scenario(1280, "populated");
  await scenario(390, "empty");
  await scenario(390, "populated");
  await scenario(1280, "populated", true);
} finally {
  await browser.close();
}
