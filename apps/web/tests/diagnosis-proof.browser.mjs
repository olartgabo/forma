// Run against a local Next server. All API responses are intercepted synthetic
// UI data; this does not call a provider or establish physical results.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const [modulePath, baseUrl] = process.argv.slice(2);
if (!modulePath || !baseUrl)
  throw new Error(
    "Usage: node diagnosis-proof.browser.mjs <playwright module path> <local web URL>",
  );
const origin = new URL(baseUrl);
if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname))
  throw new Error("Use a local web server for intercepted browser tests.");
const { chromium } = await import(pathToFileURL(modulePath).href);
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : {}),
});

const project = {
  id: "project-a",
  goal: "SYNTHETIC browser regression; no physical result",
  revision_id: "inventory-1",
  active_version_id: "version-a",
  stocks: [],
  inventory_confirmed: true,
  requirements: null,
};
const plan = {
  project_id: project.id,
  version_id: project.active_version_id,
  compiler_version: "synthetic-ui-test",
  stocks: [],
  parts: [],
  joints: [],
  checkpoints: [],
  operations: [{ id: "inspect-a", type: "inspect", depends_on: [], args: {} }],
};
const version = {
  project_id: project.id,
  version_id: plan.version_id,
  inventory_revision_id: project.revision_id,
  candidate_id: "synthetic-ui-candidate",
  plan,
  manual: { panels: [], bill_of_materials: [] },
};
const evidence = {
  id: "synthetic-diagnosis",
  kind: "model_interpretation",
  provenance: "model",
  verification_state: "unknown",
  description: "SYNTHETIC diagnosis evidence; no physical pass",
  checkpoint_ids: [],
};
function proof(saved) {
  return {
    project,
    generated_at: "2026-11-02T12:00:00Z",
    photos_omitted: 1,
    versions: [
      {
        ...version,
        state: "active",
        progress: {
          status: "not_started",
          completed_operation_ids: [],
          events: [],
          evidence: saved ? [evidence] : [],
          material_transactions: [],
          expected_remaining_stock: [],
        },
      },
    ],
  };
}
const pixel = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=",
  "base64",
);

async function scenario({ pendingExport = false } = {}) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [];
  const unexpected = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = false;
  let proofReads = 0;
  let holdExport = false;
  let releaseExport;
  const exportReleased = new Promise((resolve) => {
    releaseExport = resolve;
  });
  const downloads = [];
  page.on("download", (download) => downloads.push(download));
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    assert.equal(
      request.headers().authorization,
      "Bearer synthetic-browser-owner",
    );
    let body;
    if (path === "/api/provider/status")
      body = { configured: true, model: "synthetic-browser-model" };
    else if (path === "/api/projects")
      body = { projects: [], next_cursor: null };
    else if (path === `/api/projects/${project.id}`) body = project;
    else if (path.endsWith("/media"))
      body = {
        media: [
          {
            id: "media-a",
            project_id: project.id,
            content_type: "image/png",
            byte_count: pixel.length,
            width_px: 1,
            height_px: 1,
            evidence_linked: saved,
          },
        ],
      };
    else if (path.includes("/media/")) {
      await route.fulfill({ contentType: "image/png", body: pixel });
      return;
    } else if (path.endsWith("/plans")) body = { plans: [] };
    else if (path.endsWith(`/versions/${plan.version_id}`)) body = version;
    else if (path.endsWith("/designs/readiness"))
      body = {
        project_id: project.id,
        inventory_revision_id: project.revision_id,
        inventory_confirmed: true,
        status: "needs_input",
        missing_inputs: ["SYNTHETIC measurements unknown"],
        blockers: [],
      };
    else if (path.endsWith("/proof")) {
      proofReads++;
      body = proof(saved);
      if (holdExport) {
        holdExport = false;
        await exportReleased;
      }
    } else if (path.endsWith("/diagnose")) {
      assert.equal(request.method(), "POST");
      const input = request.postDataJSON();
      assert.equal(input.provider_transfer_consented, true);
      assert.equal(input.current_operation_id, "inspect-a");
      saved = true;
      body = {
        project_id: project.id,
        revision_id: project.revision_id,
        media_id: "media-a",
        active_version_id: plan.version_id,
        current_operation_id: "inspect-a",
        diagnosis: {
          visible_observations: ["SYNTHETIC observation"],
          hypotheses: [],
          questions_or_measurements: [],
          affected_ids: [],
          failure_type: "unknown",
        },
        diagnostics: {
          status: "ok",
          model: "synthetic-browser-model",
          elapsed_ms: 1,
        },
      };
    } else {
      unexpected.push(path);
      await route.fulfill({
        status: 500,
        json: { code: "unexpected_test_request" },
      });
      return;
    }
    await route.fulfill({ json: body });
  });
  try {
    await page.goto(new URL(`/?project=${project.id}`, origin).href);
    await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
    await page.getByRole("button", { name: "Open workbench" }).click();
    const proofPanel = page.locator(".proof-workbench");
    await proofPanel.locator(":scope > summary").click();
    await proofPanel
      .getByText("Evidence provenance (0)", { exact: true })
      .waitFor();
    const initialReads = proofReads;
    if (pendingExport) {
      holdExport = true;
      const exportStarted = page.waitForRequest("**/proof");
      await proofPanel
        .getByRole("button", { name: "Download JSON report" })
        .click();
      await exportStarted;
    }
    await page.locator("#diagnosis-photo").selectOption("media-a");
    await page.locator("#diagnosis-problem").fill("SYNTHETIC damage report");
    await page.locator("#diagnosis-operation").selectOption("inspect-a");
    await page.locator("#diagnosis-consent").check();
    await page
      .getByRole("button", { name: "Ask Muse what went wrong" })
      .click();
    await page.getByText("SYNTHETIC observation", { exact: true }).waitFor();
    await proofPanel
      .getByText("Evidence provenance (1)", { exact: true })
      .waitFor({ timeout: 5000 });
    assert.ok(proofReads > initialReads + Number(pendingExport));
    if (pendingExport) {
      releaseExport();
      await proofPanel
        .getByText(/proof snapshot changed while preparing/)
        .waitFor();
      assert.equal(downloads.length, 0, "stale export must not download");
    }
    assert.deepEqual(
      unexpected,
      [],
      "every API call is explicitly intercepted",
    );
    assert.deepEqual(errors, [], "the connected components must not crash");
    console.log(
      `PASS: diagnosis refreshes Proof${pendingExport ? " and rejects a stale export" : ""}`,
    );
  } catch (error) {
    console.error({
      errors,
      unexpected,
      page: await page.locator("body").innerText(),
    });
    throw error;
  } finally {
    releaseExport();
    await context.close();
  }
}
try {
  await scenario();
  await scenario({ pendingExport: true });
} finally {
  await browser.close();
}
