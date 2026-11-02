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
  parts: [{ id: "part-a", geometry: { width: 100, height: 150 } }],
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

async function scenario({
  pendingExport = false,
  repairCase = null,
  lostDiagnosis = null,
} = {}) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  const errors = [];
  const unexpected = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let saved = false;
  let diagnosisCalls = 0;
  let diagnosisStarted;
  const diagnosisDispatched = new Promise((resolve) => {
    diagnosisStarted = resolve;
  });
  let releaseDiagnosis;
  const diagnosisReleased = new Promise((resolve) => {
    releaseDiagnosis = resolve;
  });
  let historyCursor = "event-a";
  const simulations = [];
  const approvals = [];
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
    else if (path.endsWith("/progress"))
      body = {
        project_id: project.id,
        version_id: plan.version_id,
        last_event_id: historyCursor,
        status: "building",
        completed_operation_ids: [],
        failed_operation_ids: [],
        events: [],
        evidence: [],
        material_transactions: [],
        expected_remaining_stock: [
          {
            id: "tape-a",
            kind: "tape",
            remaining_length_mm: {
              value: historyCursor === "event-a" ? 120 : 90,
              unit: "mm",
              source: "calculated",
              confirmed: false,
            },
          },
        ],
      };
    else if (path.endsWith("/adapt/simulate")) {
      const input = request.postDataJSON();
      simulations.push(input);
      if (repairCase === "retry") {
        await route.abort("failed");
        return;
      }
      body = {
        project_id: project.id,
        base_version_id: plan.version_id,
        base_last_event_id: historyCursor,
        previews: [
          {
            preview_id: "synthetic-blocked",
            patch: input.candidates[0],
            version: repairCase === "approval" ? version : null,
            rank: repairCase === "approval" ? 1 : null,
            simulation: {
              status: repairCase === "approval" ? "feasible" : "blocked",
              blockers: [],
            },
          },
        ],
      };
    } else if (path.endsWith("/adapt/commit")) {
      approvals.push(request.postDataJSON());
      await route.abort("failed");
      return;
    } else if (path.endsWith("/designs/readiness"))
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
      diagnosisCalls++;
      assert.equal(request.method(), "POST");
      const input = request.postDataJSON();
      assert.equal(input.provider_transfer_consented, true);
      assert.equal(input.current_operation_id, "inspect-a");
      saved = lostDiagnosis !== "late";
      diagnosisStarted();
      if (lostDiagnosis && diagnosisCalls === 1) {
        if (lostDiagnosis === "cancel") await diagnosisReleased;
        await route.abort("failed").catch(() => {});
        return;
      }
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
    // A development page can paint before hydration attaches input handlers.
    // Repeat this user input only while its submit action remains disabled.
    for (let attempt = 0; attempt < 50; attempt++) {
      await page.getByLabel("Owner credential").fill("synthetic-browser-owner");
      if (
        await page.getByRole("button", { name: "Open workbench" }).isEnabled()
      )
        break;
      await page.waitForTimeout(100);
    }
    await page.getByRole("button", { name: "Open workbench" }).click();
    if (repairCase) {
      const repair = page.locator("#repair-review");
      await repair.getByRole("button", { name: "Review a repair" }).click();
      await repair
        .getByRole("combobox", { name: /^Repair/ })
        .selectOption("resize_part");
      await repair
        .getByRole("combobox", { name: /^Part/ })
        .selectOption("part-a");
      await repair.getByLabel("New width (mm)").fill("95");
      await repair
        .getByLabel("What went wrong", { exact: true })
        .fill("SYNTHETIC future part correction");
      await repair.getByRole("button", { name: "Add candidate" }).click();
      const length = repair.getByLabel(/Measured remaining tape on tape-a/);
      const confirmation = repair.getByRole("checkbox", {
        name: /I checked the remaining materials/,
      });
      const simulate = repair.getByRole("button", {
        name: "Simulate repairs",
        exact: true,
      });
      await length.fill("120");
      await confirmation.check();
      assert.equal(await simulate.isEnabled(), true);
      await simulate.click();
      if (repairCase === "retry") {
        await repair
          .getByRole("button", { name: "Retry simulation" })
          .waitFor();
      } else {
        await repair
          .getByRole("heading", { name: "Repair options", exact: true })
          .waitFor();
      }
      assert.equal(simulations.length, 1);
      if (repairCase === "approval") {
        await repair
          .getByRole("checkbox", { name: /I approve this revision/ })
          .check();
        await repair.getByRole("button", { name: "Activate revision" }).click();
        const retry = repair.getByRole("button", {
          name: "Retry approval",
          exact: true,
        });
        await retry.waitFor();
        assert.equal(await length.isDisabled(), true);
        assert.equal(await confirmation.isDisabled(), true);
        assert.equal(
          await repair
            .getByRole("button", { name: "Reload recorded work" })
            .isDisabled(),
          true,
        );
        assert.equal(await simulate.isDisabled(), true);
        const failedRetry = page.waitForEvent("requestfailed", {
          predicate: (request) =>
            new URL(request.url()).pathname.endsWith("/adapt/commit"),
        });
        await retry.click();
        await failedRetry;
        await retry.waitFor();
        assert.equal(approvals.length, 2);
        assert.deepEqual(
          approvals[1],
          approvals[0],
          "uncertain approval keeps its exact retry payload",
        );
        assert.deepEqual(errors, []);
        assert.deepEqual(unexpected, []);
        console.log(
          "PASS: uncertain approval locks stock inputs and retains exact retry",
        );
        return;
      }
      if (repairCase === "reload") {
        historyCursor = "event-b";
        await repair
          .getByRole("button", { name: "Reload recorded work" })
          .click();
        await repair.getByLabel(/calculated 90 mm/).waitFor();
        assert.equal(
          await length.inputValue(),
          "",
          "new history clears old measurements",
        );
      } else if (repairCase === "uncheck") {
        await confirmation.uncheck();
      } else {
        await length.fill("110");
      }
      assert.equal(
        await confirmation.isChecked(),
        false,
        "changed measurements need fresh confirmation",
      );
      assert.equal(await simulate.isEnabled(), false);
      assert.equal(
        await repair
          .getByRole("heading", { name: "Repair options", exact: true })
          .count(),
        0,
      );
      assert.equal(
        await repair.getByRole("button", { name: "Retry simulation" }).count(),
        0,
      );
      assert.equal(
        simulations.length,
        1,
        "no implicit simulation after inputs change",
      );
      if (repairCase === "reload") await length.fill("90");
      await confirmation.check();
      if (repairCase !== "retry") {
        await simulate.click();
        await repair
          .getByRole("heading", { name: "Repair options", exact: true })
          .waitFor();
        assert.equal(simulations.length, 2);
        const latest = simulations[1];
        assert.equal(latest.expected_last_event_id, historyCursor);
        assert.deepEqual(latest.connector_measurements, [
          {
            stock_id: "tape-a",
            remaining_length_mm:
              repairCase === "reload"
                ? 90
                : repairCase === "uncheck"
                  ? 120
                  : 110,
          },
        ]);
        assert.equal(latest.remaining_confirmed, true);
      }
      assert.deepEqual(unexpected, []);
      assert.deepEqual(errors, []);
      console.log(
        `PASS: repair confirmation and previews invalidated by ${repairCase}`,
      );
      return;
    }
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
    if (lostDiagnosis) {
      await diagnosisDispatched;
      if (lostDiagnosis === "cancel")
        await page
          .locator("#muse-diagnosis-panel")
          .getByRole("button", { name: "Cancel", exact: true })
          .click();
      if (lostDiagnosis !== "cancel")
        await page
          .locator("#muse-diagnosis-panel")
          .getByRole("alert")
          .waitFor();
      releaseExport();
      await proofPanel
        .getByText("Preparing a fresh report…", { exact: true })
        .waitFor({ state: "hidden" });
      assert.equal(
        downloads.length,
        0,
        "a report started before an ambiguous diagnosis must never download",
      );
      await proofPanel
        .getByText(/diagnosis outcome is unknown/i)
        .waitFor({ timeout: 3000 });
      assert.equal(
        await proofPanel
          .getByRole("button", { name: "Download JSON report" })
          .isDisabled(),
        true,
      );
      assert.equal(
        downloads.length,
        0,
        "ambiguous diagnosis invalidates the old export",
      );
      await proofPanel
        .getByRole("button", { name: "Refresh proof snapshot" })
        .click();
      await proofPanel
        .getByText(
          `Evidence provenance (${lostDiagnosis === "late" ? 0 : 1})`,
          { exact: true },
        )
        .waitFor();
      assert.equal(
        await proofPanel
          .getByRole("button", { name: "Download JSON report" })
          .isDisabled(),
        true,
        "a snapshot cannot prove an unknown operation finished",
      );
      assert.equal(await page.locator("#diagnosis-consent").isChecked(), false);
      const acknowledgement = proofPanel.getByRole("checkbox", {
        name: /Use current saved snapshot/,
      });
      await acknowledgement.check();
      if (lostDiagnosis === "late") {
        saved = true;
        await proofPanel
          .getByRole("button", { name: "Refresh proof snapshot" })
          .click();
        await proofPanel
          .getByText("Evidence provenance (1)", { exact: true })
          .waitFor();
        assert.equal(await acknowledgement.isChecked(), false);
        await acknowledgement.check();
      }
      const downloaded = page.waitForEvent("download");
      await proofPanel
        .getByRole("button", { name: "Download JSON report" })
        .click();
      await downloaded;
      await proofPanel.getByText(/diagnosis outcome is unknown/i).waitFor();
      assert.equal(
        downloads.length,
        1,
        "explicit acknowledgement permits an as-of export",
      );
      assert.equal(
        diagnosisCalls,
        1,
        "refresh and export never retry a provider request",
      );
      if (lostDiagnosis === "network") {
        await page.locator("#diagnosis-consent").check();
        await page
          .getByRole("button", { name: "Ask Muse what went wrong" })
          .click();
        await page
          .getByText("SYNTHETIC observation", { exact: true })
          .waitFor();
        await proofPanel.getByText(/diagnosis outcome is unknown/i).waitFor();
        assert.equal(
          await proofPanel
            .getByRole("button", { name: "Download JSON report" })
            .isDisabled(),
          true,
          "a new success cannot settle an earlier unknown request",
        );
        assert.equal(
          await acknowledgement.count(),
          0,
          "a new diagnosis invalidates the as-of acknowledgement",
        );
        assert.equal(diagnosisCalls, 2);
      }
      assert.deepEqual(errors, []);
      assert.deepEqual(unexpected, []);
      console.log(
        `PASS: ${lostDiagnosis} diagnosis invalidates exports and retains uncertainty after refresh`,
      );
      return;
    }
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
    releaseDiagnosis();
    await context.close();
  }
}
try {
  await scenario({ pendingExport: true, lostDiagnosis: "cancel" });
  await scenario({ pendingExport: true, lostDiagnosis: "network" });
  await scenario({ pendingExport: true, lostDiagnosis: "late" });
  await scenario();
  await scenario({ pendingExport: true });
  for (const repairCase of ["edit", "reload", "uncheck", "retry", "approval"])
    await scenario({ repairCase });
} finally {
  await browser.close();
}
