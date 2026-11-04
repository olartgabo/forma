// Replays actual API responses exported by design-candidates-fixture.py in a
// local intercepted browser. SYNTHETIC inputs; MetaMuse is an offline scripted
// transport recorded from the real route; no provider and no physical pass.
// Covers search → comparison → probe (with a stale-response race) → MetaMuse
// comparison → explicit selection whose response is lost, recovered after a
// reload with the same key → the existing, separate plan approval.
import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl, fixturePath] = process.argv.slice(2);
if (!modulePath || !baseUrl || !fixturePath)
  throw new Error(
    "Usage: node design-candidates.browser.mjs <playwright> <local URL> <fixture JSON>",
  );
const origin = new URL(baseUrl);
if (!["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))
  throw new Error("Only a local intercepted browser is permitted");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const { project, search, probe, select, version, muse } = fixture;
const base = `/api/projects/${project.id}`;
const [first, second] = search.candidates;
// Stands in for a search after an inventory change: same designs, another
// search identity. Test-made; every other response is recorded from the API.
const searchB = { ...search, search_id: "e".repeat(64) };
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch(
  process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
);

async function open(page) {
  await page.goto(`${origin.origin}/?project=${project.id}`);
  await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
  await page.getByRole("button", { name: "Open workbench" }).click();
  return page.getByRole("region", {
    name: "Search designs from your saved stock",
  });
}

try {
  for (const width of [390, 1280]) {
    const page = await (
      await browser.newContext({
        viewport: { width, height: 900 },
        serviceWorkers: "block",
      })
    ).newPage();
    page.setDefaultTimeout(30000);
    const errors = [];
    const unexpected = [];
    const posts = [];
    const researchBodies = [];
    let saved = false;
    let selectCalls = 0;
    let probeCalls = 0;
    let searches = 0;
    let museCalls = 0;
    let releaseProbe = () => {};
    const heldProbe = new Promise((resolve) => (releaseProbe = resolve));
    let releaseResearch = () => {};
    const heldResearch = new Promise((resolve) => (releaseResearch = resolve));
    let markResearchStarted = () => {};
    let delayResearchAvailability = false;
    let releaseResearchAvailability = () => {};
    const heldAvailability = new Promise(
      (resolve) => (releaseResearchAvailability = resolve),
    );
    let releaseClearance = () => {};
    const heldClearance = new Promise(
      (resolve) => (releaseClearance = resolve),
    );
    let markClearanceStarted = () => {};
    const clearanceStarted = new Promise(
      (resolve) => (markClearanceStarted = resolve),
    );
    const researchStarted = new Promise(
      (resolve) => (markResearchStarted = resolve),
    );
    page.on("pageerror", (e) => errors.push(e.message));
    await page.context().route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin.origin) {
        unexpected.push(`external ${url.origin}`);
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const method = request.method();
      if (method === "POST") {
        const body = request.postDataJSON();
        if (url.pathname === `${base}/synthesis/research`) {
          researchBodies.push(body);
          assert.deepEqual(Object.keys(body).sort(), [
            "consented",
            "expected_inventory_revision_id",
            "idempotency_key",
            "needs_plug_clearance",
            "use_case",
          ]);
          assert.equal(body.consented, true);
          assert.equal(
            body.expected_inventory_revision_id,
            project.revision_id,
          );
          const common = {
            project_id: project.id,
            inventory_revision_id: project.revision_id,
          };
          if (body.needs_plug_clearance) {
            if (researchBodies.length === 3) {
              markClearanceStarted();
              await heldClearance;
            }
            return route
              .fulfill({
                json: {
                  ...common,
                  coverage: "not_run",
                  decision: "unsupported",
                  reason:
                    "Plug clearance is essential and has no supported check.",
                  findings: [],
                },
              })
              .catch(() => {});
          }
          if (body.use_case === "reading_stand" && researchBodies.length === 2)
            return route.fulfill({
              status: 409,
              json: { code: "stale_version" },
            });
          if (body.use_case === "reading_stand")
            return route.fulfill({
              json: {
                ...common,
                coverage: "unavailable",
                decision: "eligible",
                reason: "The existing stand search found checked proposals.",
                findings: [],
                search: searchB,
              },
            });
          const checked = {
            ...common,
            coverage: "complete",
            decision: "eligible",
            reason: "SYNTHETIC recommendation over checked designs.",
            findings: [
              {
                title: "SYNTHETIC taped brace reference",
                claim: "An example uses a taped brace.",
                url: "https://example.com/stand",
              },
              {
                title: "SYNTHETIC deeper base reference",
                claim: "An example uses a deeper base.",
                url: "https://example.com/deeper-base",
              },
            ],
            search: searchB,
            recommended_candidate_id: second.candidate_id,
            recommendation_source_index: 1,
          };
          if (researchBodies.length === 5) {
            markResearchStarted();
            await heldResearch;
            return route.fulfill({ json: checked }).catch(() => {});
          }
          return route.fulfill({ json: { ...checked, replayed: true } });
        }
        posts.push([url.pathname, body]);
        if (url.pathname === `${base}/synthesis/search`) {
          assert.equal(
            body.expected_inventory_revision_id,
            project.revision_id,
          );
          assert.equal(body.expected_active_version_id, null);
          assert.equal(body.expected_last_event_id, null);
          searches += 1;
          return route.fulfill({ json: searches === 1 ? search : searchB });
        }
        if (url.pathname === `${base}/synthesis/probe`) {
          probeCalls += 1;
          assert.equal(body.search_id, search.search_id);
          assert.equal(body.parameter, "footprint_depth_mm");
          assert.equal(body.value_mm, fixture.probe_value);
          assert.deepEqual(body.design, first.design);
          // The first answer arrives after the selector has changed.
          if (probeCalls === 1) await heldProbe;
          return route.fulfill({ json: probe });
        }
        if (url.pathname === `${base}/synthesis/muse-explanations`) {
          assert.equal(body.provider_context_consented, true);
          assert.equal(body.search_id, search.search_id);
          assert.equal("design" in body, false);
          museCalls += 1;
          // The second request completes on the server but its answer is lost.
          if (museCalls === 2) return route.abort("connectionreset");
          return route.fulfill({ json: muse });
        }
        if (url.pathname === `${base}/synthesis/select`) {
          selectCalls += 1;
          assert.equal(body.user_selected, true);
          assert.deepEqual(body.design, second.design);
          assert.equal(body.search_id, searchB.search_id);
          // The server saves the preview but the first response is lost.
          saved = true;
          if (selectCalls === 1) return route.abort("connectionreset");
          return route.fulfill({ json: { ...select, replayed: true } });
        }
        if (url.pathname === `${base}/plans/${version.version_id}/activate`) {
          assert.equal(body.user_approved, true);
          return route.fulfill({ json: fixture.activation });
        }
        unexpected.push(`POST ${url.pathname}`);
        return route.fulfill({ status: 500, json: { code: "unexpected" } });
      }
      if (
        url.pathname === `${base}/synthesis/research` &&
        delayResearchAvailability
      )
        await heldAvailability;
      const replay = new Map([
        ["/api/provider/status", { configured: true }],
        ["/api/projects", { projects: [], next_cursor: null }],
        [base, project],
        [`${base}/media`, { media: [] }],
        [`${base}/designs/readiness`, fixture.readiness],
        [`${base}/synthesis/research`, { enabled: true }],
        [`${base}/plans`, saved ? fixture.plans_after : fixture.plans_before],
        [`${base}/versions/${version.version_id}`, version],
      ]);
      if (replay.has(url.pathname))
        return route.fulfill({ json: replay.get(url.pathname) });
      // Other panels (fabrication preview etc.) are outside this check.
      return route.fulfill({
        status: 503,
        json: { code: "unavailable", message: "Not part of this fixture" },
      });
    });
    let panel = await open(page);
    await panel
      .getByRole("button", { name: "Search stock-feasible designs" })
      .click();
    const designA = panel.getByRole("article", { name: "Design A" });
    await designA.waitFor();
    await panel.getByRole("article", { name: "Design B" }).waitFor();
    for (const name of ["Support panel", "Base panel", "Rear brace"])
      assert.equal(
        await designA.getByText(name, { exact: true }).count(),
        1,
        name,
      );
    const textA = await designA.innerText();
    assert.match(textA, /Brace \(calculated\)/);
    assert.match(textA, /Needs measurements/);
    assert.match(textA, /Not modeled/);
    assert.match(textA, /Not verified/);
    assert.doesNotMatch(textA, /Fails a modeled check/);
    assert.match(
      await panel.innerText(),
      new RegExp(`Checked ${search.nodes_evaluated} of ${search.nodes_total}`),
    );

    // Probe race: a late answer must not attach to a changed selector.
    await panel
      .getByRole("button", { name: "Try a size change" })
      .first()
      .click();
    const value = panel.getByLabel("New value");
    await panel.getByLabel("Dimension").selectOption("footprint_depth_mm");
    await value.selectOption(String(fixture.probe_value));
    await panel.getByRole("button", { name: "Check this change" }).click();
    const other = (await value.locator("option").allTextContents())
      .map((text) => text.replace(" mm", ""))
      .find(
        (text) =>
          /^[0-9.]+$/.test(text) && Number(text) !== fixture.probe_value,
      );
    await value.selectOption(other);
    releaseProbe();
    // The check button re-enables once the late answer has been handled.
    await page.waitForFunction(() =>
      [...document.querySelectorAll(".design-probe button")].some(
        (b) => b.textContent === "Check this change" && !b.disabled,
      ),
    );
    assert.equal(await panel.getByText(/Engine result for/).count(), 0);
    await value.selectOption(String(fixture.probe_value));
    await panel.getByRole("button", { name: "Check this change" }).click();
    await panel.getByRole("article", { name: "Changed design" }).waitFor();
    assert.match(
      await panel.innerText(),
      new RegExp(
        `Engine result for Base depth = ${fixture.probe_value} mm: still fits your stock. Recalculated pieces: stand-base, stand-brace`,
      ),
    );

    // MetaMuse needs explicit consent and only explains engine results.
    const ask = panel.getByRole("button", { name: "Ask MetaMuse" });
    assert.equal(await ask.isDisabled(), true);
    await panel
      .getByLabel("Share these proposed designs (no photos) with MetaMuse")
      .check();
    await ask.click();
    const answer = panel.getByRole("article", { name: "MetaMuse comparison" });
    await answer.waitFor();
    assert.match(
      await answer.innerText(),
      /Model wording is not a physical test/,
    );
    await answer
      .getByRole("article", { name: "Engine check requested by MetaMuse" })
      .waitFor();
    assert.equal(
      await answer
        .getByRole("button", { name: "Use the changed design" })
        .count(),
      1,
    );

    // A lost answer recovered after a new search is history, not a choice.
    await ask.click();
    const museRetry = panel.getByRole("button", {
      name: "Retry the unresolved MetaMuse request",
    });
    await museRetry.waitFor();
    await panel
      .getByRole("button", { name: "Search stock-feasible designs" })
      .click();
    await panel.getByRole("article", { name: "Design A" }).waitFor();
    await panel
      .getByLabel("Share these proposed designs (no photos) with MetaMuse")
      .check();
    await museRetry.click();
    const earlier = panel.getByRole("article", {
      name: "Earlier MetaMuse comparison",
    });
    await earlier.waitFor();
    assert.match(await earlier.innerText(), /about an earlier search/);
    assert.equal(
      await earlier
        .getByRole("button", { name: "Use the changed design" })
        .count(),
      0,
    );
    const museBodies = posts.filter(([path]) =>
      path.endsWith("/muse-explanations"),
    );
    assert.equal(museBodies.length, 3);
    assert.deepEqual(museBodies[1][1], museBodies[2][1]);
    assert.deepEqual(
      posts.map(([path]) => path.split("/").pop()),
      [
        "search",
        "probe",
        "probe",
        "muse-explanations",
        "muse-explanations",
        "search",
        "muse-explanations",
      ],
    );

    // Research must have fresh consent, and a required unsupported check
    // clears earlier design choices instead of silently relaxing the brief.
    const research = panel.getByRole("group", {
      name: "Find ideas for this build",
    });
    const start = research.getByRole("button", {
      name: "Research and check ideas",
    });
    const consent = research.getByLabel(
      "Share this brief and option comparisons with MetaMuse",
    );
    const clearance = research.getByLabel("Plug clearance is essential");
    assert.equal(await start.isDisabled(), true);
    const useCase = research.getByRole("combobox", {
      name: "What are you making?",
    });
    await useCase.selectOption("reading_stand");
    await consent.check();
    await start.click();
    await research.getByText("Research unavailable", { exact: true }).waitFor();
    assert.equal(
      await panel
        .getByRole("button", { name: "Use design B" })
        .isEnabled({ timeout: 2000 }),
      true,
      "ordinary designs remain usable after a provider failure",
    );
    assert.equal(await earlier.isVisible(), true);

    await consent.check();
    await start.click();
    await research
      .getByText("Your inventory changed. Reload it before researching again.")
      .waitFor();
    assert.equal(
      await panel.getByRole("button", { name: "Use design B" }).count(),
      0,
      "stale results clear the earlier stock choices",
    );

    await panel
      .getByRole("button", { name: "Search stock-feasible designs" })
      .click();
    await panel.getByRole("article", { name: "Design A" }).waitFor();
    await clearance.check();
    await research.getByText(/no glue. Plug clearance is essential/).waitFor();
    await consent.check();
    await start.click();
    await clearanceStarted;
    await research.getByRole("button", { name: "Stop waiting" }).click();
    releaseClearance();

    delayResearchAvailability = true;
    await page.reload();
    panel = await open(page);
    await research
      .getByText("Plug clearance is essential", { exact: true })
      .waitFor();
    assert.equal(
      await panel
        .getByRole("button", { name: "Search stock-feasible designs" })
        .isDisabled(),
      true,
      "stock search cannot bypass clearance while availability is unresolved",
    );
    delayResearchAvailability = false;
    releaseResearchAvailability();
    const clearanceRetry = research.getByRole("button", {
      name: "Retry the same research request",
    });
    await clearanceRetry.waitFor();
    assert.equal(await clearance.isChecked(), true);
    assert.equal(
      await panel
        .getByRole("button", { name: "Search stock-feasible designs" })
        .isDisabled(),
      true,
      "a restored clearance requirement still blocks stock-only search",
    );
    await consent.check();
    await clearanceRetry.click();
    await research
      .getByText("This requirement is outside the supported checks")
      .waitFor();
    assert.equal(
      await panel.getByRole("button", { name: "Use design B" }).count(),
      0,
    );

    assert.deepEqual(researchBodies[2], researchBodies[3]);

    // A late research response must not replace ordinary search. Recover
    // it with the retained body, then require explicit review and selection.
    await clearance.uncheck();
    await consent.check();
    await start.click();
    await researchStarted;
    await panel
      .getByRole("button", { name: "Search stock-feasible designs" })
      .click();
    await panel.getByRole("article", { name: "Design A" }).waitFor();
    releaseResearch();
    const retryResearch = research.getByRole("button", {
      name: "Retry the same research request",
    });
    await retryResearch.waitFor();
    assert.equal(
      await research.getByText("Checked designs to review").count(),
      0,
    );
    assert.equal(await retryResearch.isDisabled(), true);
    await consent.check();
    await retryResearch.click();
    const source = research.getByRole("link", {
      name: "SYNTHETIC taped brace reference",
    });
    await source.waitFor();
    assert.equal(
      await source.getAttribute("href"),
      "https://example.com/stand",
    );
    await research
      .getByRole("listitem")
      .filter({ hasText: "Source used for the recommendation" })
      .getByRole("link", { name: "SYNTHETIC deeper base reference" })
      .waitFor();
    assert.deepEqual(researchBodies[4], researchBodies[5]);
    assert.equal(await panel.getByText("Suggested by research").count(), 0);
    await research
      .getByRole("button", { name: "Review checked designs" })
      .click();
    const reviewedA = panel.getByRole("article", { name: "Design A" });
    const reviewedB = panel.getByRole("article", { name: "Design B" });
    await reviewedB
      .getByText("Suggested by research")
      .waitFor({ timeout: 2000 });
    assert.equal(await reviewedA.getByText("Suggested by research").count(), 0);
    assert.match(
      await reviewedB.innerText(),
      /SYNTHETIC recommendation over checked designs/,
    );
    assert.equal(
      await reviewedB
        .getByRole("link", { name: "SYNTHETIC deeper base reference" })
        .getAttribute("href"),
      "https://example.com/deeper-base",
    );
    assert.equal(
      await reviewedB.getByText("An example uses a deeper base.").count(),
      1,
    );
    assert.equal(selectCalls, 0, "research review must not save a preview");

    // Choose design B; the response is lost, then the page is reloaded.
    await panel.getByRole("button", { name: "Use design B" }).click();
    await panel
      .getByRole("button", { name: "Retry saving that design" })
      .waitFor();
    // A corrupt MetaMuse receipt must not hide or erase the design choice.
    await page.evaluate(async (projectId) => {
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode("synthetic-browser-owner"),
      );
      const owner = Array.from(new Uint8Array(digest), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      localStorage.setItem(
        `forma-design-muse-pending-v1:${owner}:${projectId}`,
        "{corrupt",
      );
    }, project.id);
    await page.reload();
    panel = await open(page);
    const retry = panel.getByRole("button", {
      name: "Retry saving that design",
    });
    await retry.waitFor();
    await panel
      .getByRole("button", { name: "Clear the unverifiable MetaMuse request" })
      .click();
    assert.equal(await retry.count(), 1);
    assert.equal(
      await page.evaluate(
        () =>
          Object.keys(localStorage).filter((k) =>
            k.startsWith("forma-design-select-pending-v1:"),
          ).length,
      ),
      1,
    );
    await retry.click();
    await panel.getByText(/Saved as a proposed plan/).waitFor();
    const selects = posts.filter(([path]) =>
      path.endsWith("/synthesis/select"),
    );
    assert.equal(selects.length, 2);
    assert.deepEqual(selects[0][1], selects[1][1]);
    assert.equal(await retry.count(), 0);
    assert.equal(
      posts.some(([path]) => path.endsWith("/activate")),
      false,
      "selection must not approve",
    );

    // Approval is the existing, separate transaction.
    const approve = page.getByRole("button", { name: "Approve this plan" });
    await approve.waitFor();
    assert.equal(await approve.isDisabled(), true);
    await page
      .getByLabel("I reviewed this plan and its required physical checks.")
      .check();
    await approve.click();
    await page.waitForFunction(
      () => !document.querySelector(".design-candidates"),
    );
    assert.equal(
      posts.filter(([path]) => path.endsWith("/activate")).length,
      1,
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    assert.equal(overflow, false, `horizontal overflow at ${width}px`);
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      `PASS ${width}px research consent, provider fallback, stale and unsupported clearance, late result discarded, exact replay and cited candidate review; existing search, probe, comparison, selection recovery and separate approval; SYNTHETIC responses only`,
    );
    await page.context().close();
  }
} finally {
  await browser.close();
}
