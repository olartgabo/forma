(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId("stand-loads");
  const stage = byId("stand-stage");
  let plan;
  let last;
  let view = "iso";
  let revision = 0;
  const num = (n) => Number(n.toPrecision(6)).toString();
  const clean = (s) => s.replaceAll("_", " ");
  const svg = (tag, attrs) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs))
      element.setAttribute(key, value);
    return element;
  };
  function changed() {
    revision++;
    if (last)
      byId("stand-status").textContent =
        "Inputs changed. Displayed stand result is historical; evaluate again.";
  }
  form.addEventListener("input", changed);
  byId("stand-plan-json").addEventListener("input", changed);
  function draw() {
    const target = byId("stand-view");
    target.replaceChildren();
    if (!last) return;
    const geometry = last.selected_geometry ?? last.reference_geometry;
    const referenceOnly = last.selected_prefix === 0 || !last.selected_geometry;
    byId("stand-geometry-caption").textContent = referenceOnly
      ? "DASHED PLANNED TARGET REFERENCE ONLY — this is not the physical shape/contact of the selected construction stage."
      : "Canonical nominal geometry for the hypothetically assembled stage. Not an observed physical shape.";
    const overlay = last.report?.overlays?.[0];
    const points = geometry.facets.flatMap((f) => f.vertices);
    if (overlay) points.push(overlay.center_of_mass, ...overlay.critical_edge);
    const project = (p) =>
      view === "front"
        ? [p.x, -p.z]
        : view === "side"
          ? [p.y, -p.z]
          : [((p.x - p.y) * Math.sqrt(3)) / 2, (p.x + p.y) / 2 - p.z];
    const projected = points.map(project);
    const minX = Math.min(...projected.map((p) => p[0]));
    const maxX = Math.max(...projected.map((p) => p[0]));
    const minY = Math.min(...projected.map((p) => p[1]));
    const maxY = Math.max(...projected.map((p) => p[1]));
    const scale = 370 / Math.max(maxX - minX, maxY - minY, 0.001);
    const xy = (p) => {
      const q = project(p);
      return [65 + (q[0] - minX) * scale, 45 + (q[1] - minY) * scale];
    };
    if (points.some((p) => xy(p).some((v) => !Number.isFinite(v)))) {
      target.textContent =
        "Canonical coordinates cannot be displayed at this numerical scale; inspect JSON.";
      return;
    }
    const image = svg("svg", {
      viewBox: "0 0 520 470",
      role: "img",
      "aria-label": referenceOnly
        ? "Isometric planned stand reference, not the selected stage"
        : "Canonical assembled stand diagnostic projection",
    });
    const colors = ["#8fb9a8", "#edc77e", "#9eb9cf", "#c3a9c5"];
    geometry.facets.forEach((facet, i) => {
      image.append(
        svg("polygon", {
          points: facet.vertices.map((p) => xy(p).join(",")).join(" "),
          fill: referenceOnly ? "none" : colors[i % colors.length],
          "fill-opacity": "0.6",
          stroke: "#274c40",
          "stroke-width": "2",
          "stroke-dasharray": referenceOnly ? "7 4" : "none",
        }),
      );
      const center = xy(facet.centroid);
      if (center.every(Number.isFinite)) {
        const text = svg("text", {
          x: center[0] + 5,
          y: center[1] - 5,
          "font-size": "15",
          fill: "#172b36",
        });
        text.textContent = String(i + 1);
        image.append(text);
      }
    });
    if (overlay) {
      const center = xy(overlay.center_of_mass);
      image.append(
        svg("circle", {
          cx: center[0],
          cy: center[1],
          r: "6",
          fill: "#111827",
        }),
      );
      image.append(
        svg("polyline", {
          points: overlay.critical_edge.map((p) => xy(p).join(",")).join(" "),
          fill: "none",
          stroke: "#a15c00",
          "stroke-width": "5",
        }),
      );
    }
    const title = svg("text", {
      x: "12",
      y: "22",
      fill: "#172b36",
      "font-size": "14",
    });
    title.textContent = `${view === "iso" ? "Isometric 3D projection" : clean(view) + " projection"} · z up · canonical metres`;
    image.append(title);
    target.append(image);
    const legend = document.createElement("ol");
    geometry.facets.forEach((facet) => {
      const item = document.createElement("li");
      item.textContent = `${facet.facet_id} — source ${facet.part_id}; ${num(facet.area_fraction * 100)}% of source sheet area`;
      legend.append(item);
    });
    target.append(legend);
  }
  function show(result) {
    last = result;
    byId("stand-stage-label").textContent = result.selected_stage_label;
    byId("stand-status").textContent = result.report
      ? `Compiled stand result: ${clean(result.report.status)} (hypothetical static model).`
      : `No selected-stage stability report. ${result.blockers.join(" ")}`;
    byId("stand-full-result").textContent = JSON.stringify(result, null, 2);
    const operations = byId("stand-operations");
    operations.replaceChildren();
    result.operations.forEach((op) => {
      const item = document.createElement("li");
      const state =
        op.type === "functional_test"
          ? "physical test never simulated"
          : op.selected_in_prefix
            ? "hypothetical completion"
            : "not selected";
      item.textContent = `${op.id} — ${clean(op.type)} — ${state}. Prerequisites: ${op.depends_on.join(", ") || "none"}. Planned attachment effects: ${op.attached_joint_ids.join(", ") || "none"}; detach effects: ${op.detached_joint_ids.join(", ") || "none"}.`;
      const description = document.createElement("p");
      description.textContent = `Existing manual: ${op.instruction} Tools: ${op.tools.join(", ")}.`;
      item.append(description);
      operations.append(item);
    });
    const metrics = byId("stand-result");
    metrics.replaceChildren();
    if (result.report) {
      for (const entry of result.report.results) {
        const p = document.createElement("p");
        p.textContent = `${entry.check_type}: ${clean(entry.status)}. ${entry.explanation}`;
        metrics.append(p);
      }
      for (const overlay of result.report.overlays) {
        const p = document.createElement("p");
        p.textContent = `Combined COM: (${num(overlay.center_of_mass.x * 1000)}, ${num(overlay.center_of_mass.y * 1000)}, ${num(overlay.center_of_mass.z * 1000)}) mm. Signed clearance: ${num(overlay.signed_margin_m * 1000)} mm. Restoring moment: ${num(overlay.restoring_moment_n_m)} N·m. Black point = combined COM; thick edge = governing support edge.`;
        metrics.append(p);
      }
    }
    draw();
    byId("stand-download").disabled = false;
  }
  async function inspect(loads = null) {
    if (!plan) return;
    const own = ++revision;
    byId("run-stand").disabled = true;
    byId("stand-error").textContent = "";
    byId("stand-status").textContent =
      "Inspecting canonical plan… previous result is historical.";
    try {
      const response = await fetch("/inspect-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan,
          completed_prefix: Number(stage.value),
          loads,
        }),
        signal: AbortSignal.timeout(15000),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Plan inspection failed");
      if (own !== revision) return;
      show(result);
    } catch (error) {
      if (own === revision) {
        byId("stand-error").textContent = error.message;
        byId("stand-status").textContent =
          "Inspection failed. Previous display is historical; it cannot verify the new inputs.";
      }
    } finally {
      byId("run-stand").disabled = false;
    }
  }
  function loadPlan(value) {
    plan = value.version?.plan ?? value.plan ?? value;
    if (!Array.isArray(plan.operations) || !Array.isArray(plan.parts))
      throw new Error("Provide a compiled BuildPlan with operations and parts");
    last = null;
    byId("stand-download").disabled = true;
    byId("stand-view").replaceChildren();
    byId("stand-result").replaceChildren();
    byId("stand-plan-json").value = JSON.stringify(plan, null, 2);
    stage.replaceChildren();
    const initial = document.createElement("option");
    initial.value = "0";
    initial.textContent = "0 — planned target reference; no work assumed";
    stage.append(initial);
    plan.operations.forEach((op, i) => {
      const option = document.createElement("option");
      option.value = String(i + 1);
      option.textContent = `${i + 1} — ${clean(op.type)} (${op.id})`;
      stage.append(option);
    });
    const masses = byId("stand-part-masses");
    masses.replaceChildren();
    const legend = document.createElement("legend");
    legend.textContent = "Source part plus allocated connectors (g)";
    masses.append(legend);
    plan.parts.forEach((part) => {
      const label = document.createElement("label");
      label.textContent = part.id;
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.dataset.part = part.id;
      input.setAttribute(
        "aria-label",
        `${part.id} mass including connector share in grams`,
      );
      label.append(input);
      masses.append(label);
    });
    form.reset();
    inspect();
  }
  async function loadSample() {
    try {
      const response = await fetch("/sample-plan");
      if (!response.ok) throw new Error("Could not load compiled sample");
      loadPlan(await response.json());
    } catch (error) {
      byId("stand-error").textContent = error.message;
    }
  }
  byId("load-stand").addEventListener("click", loadSample);
  byId("import-stand").addEventListener("click", () => {
    try {
      loadPlan(JSON.parse(byId("stand-plan-json").value));
    } catch (error) {
      byId("stand-error").textContent = error.message;
    }
  });
  stage.addEventListener("change", () => inspect());
  document.querySelectorAll("[data-stand-view]").forEach((button) =>
    button.addEventListener("click", () => {
      view = button.dataset.standView;
      draw();
    }),
  );
  byId("stand-example").addEventListener("click", () => {
    form.querySelectorAll("[data-part]").forEach((input, i) => {
      input.value = String(20 + 5 * i);
    });
    const values = {
      device_mass_g: 200,
      device_x_mm: 0,
      device_y_mm: 70,
      device_z_mm: 110,
      required_margin_mm: 0,
      tolerance_mm: 0.000001,
      gravity_m_s2: 9.81,
    };
    for (const [key, value] of Object.entries(values))
      form.elements.namedItem(key).value = value;
    form.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = true;
    });
    changed();
    byId("stand-status").textContent =
      "Invented load values and assumptions loaded. These are not measurements. Select a stage and explicitly evaluate.";
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const loads = { part_mass_g: {} };
    for (const input of form.querySelectorAll("input")) {
      const value =
        input.type === "checkbox"
          ? input.checked
          : input.value === ""
            ? null
            : Number(input.value);
      if (input.dataset.part) loads.part_mass_g[input.dataset.part] = value;
      else loads[input.name] = value;
    }
    inspect(loads);
  });
  byId("stand-download").addEventListener("click", () => {
    if (!last) return;
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { ...last, feedback: byId("stand-notes").value },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "forma-compiled-stand-feedback.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  loadSample();
})();
