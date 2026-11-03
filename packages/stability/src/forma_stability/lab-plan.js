(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId("stand-loads");
  const stage = byId("stand-stage");
  let plan;
  let last;
  const camera = { yaw: 315, elevation: 30, zoom: 1 };
  const pointers = new Map();
  let cameraFrame = null;
  const viewport = byId("stand-view");
  const clamp = (value, minimum, maximum) =>
    Math.max(minimum, Math.min(maximum, value));
  function normalizeCamera() {
    camera.yaw = ((camera.yaw % 360) + 360) % 360;
    camera.elevation = clamp(camera.elevation, -85, 85);
    camera.zoom = clamp(camera.zoom, 0.4, 3);
    byId("stand-camera-state").textContent =
      `Rotation ${Math.round(camera.yaw)}\u00b0 \u00b7 elevation ${Math.round(camera.elevation)}\u00b0 \u00b7 zoom ${camera.zoom.toFixed(2)}\u00d7`;
    byId("stand-zoom").value = String(camera.zoom);
    viewport.dataset.yaw = String(camera.yaw);
    viewport.dataset.elevation = String(camera.elevation);
    viewport.dataset.zoom = String(camera.zoom);
  }
  function redrawCamera() {
    normalizeCamera();
    if (cameraFrame !== null) return;
    cameraFrame = requestAnimationFrame(() => {
      cameraFrame = null;
      draw();
    });
  }
  function resetCamera() {
    Object.assign(camera, { yaw: 315, elevation: 30, zoom: 1 });
    redrawCamera();
  }
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
  byId("stand-snapshot").addEventListener("input", changed);
  byId("stand-checks").addEventListener("input", changed);
  function draw() {
    const target = byId("stand-view");
    target.replaceChildren();
    if (!last) return;
    const geometry = last.stage_analysis?.facets?.length
      ? last.stage_analysis
      : (last.selected_geometry ?? last.reference_geometry);
    const referenceOnly =
      !last.stage_analysis?.facets?.length &&
      (last.selected_prefix === 0 || !last.selected_geometry);
    byId("stand-geometry-caption").textContent = referenceOnly
      ? "DASHED PLANNED TARGET REFERENCE ONLY \u2014 this is not the physical shape/contact of the selected construction stage."
      : last.stage_analysis
        ? "Explicit hypothetical stage poses and contacts. Separate components are evaluated separately; no physical observation is claimed."
        : "Canonical nominal geometry for the hypothetically assembled stage. Not an observed physical shape.";
    const overlays = last.stage_analysis
      ? (last.stage_analysis_world_overlays ?? [])
      : (last.report?.overlays ?? []);
    const modelPoints = geometry.facets.flatMap((f) => f.vertices);
    // The camera fits only canonical model bounds, never COM or screen extents.
    // Rotation/zoom cannot alter physical inputs, report identity, or these bounds.
    const bounds = Object.fromEntries(
      ["x", "y", "z"].map((axis) => [
        axis,
        [
          Math.min(...modelPoints.map((p) => p[axis])),
          Math.max(...modelPoints.map((p) => p[axis])),
        ],
      ]),
    );
    const center = Object.fromEntries(
      ["x", "y", "z"].map((axis) => [
        axis,
        bounds[axis][0] / 2 + bounds[axis][1] / 2,
      ]),
    );
    const radius = Math.max(
      Math.hypot(
        ...["x", "y", "z"].map(
          (axis) => (bounds[axis][1] - bounds[axis][0]) / 2,
        ),
      ),
      0.0005,
    );
    const yaw = (camera.yaw * Math.PI) / 180;
    const elevation = (camera.elevation * Math.PI) / 180;
    const projectVector = (x, y, z) => {
      const horizontal = -Math.sin(yaw) * x + Math.cos(yaw) * y;
      return [
        Math.cos(yaw) * x + Math.sin(yaw) * y,
        Math.sin(elevation) * horizontal - Math.cos(elevation) * z,
        Math.cos(elevation) * horizontal + Math.sin(elevation) * z,
      ];
    };
    const project = (p) =>
      projectVector(p.x - center.x, p.y - center.y, p.z - center.z);
    const scale = (185 * camera.zoom) / radius;
    const xy = (p) => {
      const q = project(p);
      return [260 + q[0] * scale, 240 + q[1] * scale];
    };
    const points = [...modelPoints, ...geometry.facets.map((f) => f.centroid)];
    for (const overlay of overlays)
      points.push(overlay.center_of_mass, ...overlay.critical_edge);
    if (
      !Number.isFinite(radius) ||
      points.some((p) => xy(p).some((v) => !Number.isFinite(v)))
    ) {
      target.textContent =
        "Canonical coordinates cannot be displayed at this numerical scale; inspect JSON.";
      return;
    }
    const image = svg("svg", {
      viewBox: "0 0 520 470",
      role: "img",
      "aria-label": referenceOnly
        ? "Rotatable planned stand reference, not the selected stage"
        : "Rotatable canonical stand diagnostic projection",
    });
    const colors = ["#8fb9a8", "#edc77e", "#9eb9cf", "#c3a9c5"];
    const orderedFacets = geometry.facets
      .map((facet, i) => ({ facet, i, depth: project(facet.centroid)[2] }))
      .sort((a, b) => a.depth - b.depth || a.i - b.i);
    orderedFacets.forEach(({ facet, i }) => {
      image.append(
        svg("polygon", {
          points: facet.vertices.map((p) => xy(p).join(",")).join(" "),
          fill: referenceOnly ? "none" : colors[i % colors.length],
          "fill-opacity": "0.6",
          stroke: "#274c40",
          "stroke-width": "2",
          "stroke-dasharray": referenceOnly ? "7 4" : "none",
          "data-facet-id": facet.facet_id,
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
    for (const overlay of overlays) {
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
    title.textContent = "3D orbit \u00b7 canonical metres \u00b7 display only";
    for (const [axis, vector, color] of [
      ["x", [1, 0, 0], "#a63939"],
      ["y", [0, 1, 0], "#26744d"],
      ["z", [0, 0, 1], "#315f9b"],
    ]) {
      const q = projectVector(...vector);
      const x = 465 + q[0] * 28;
      const y = 415 + q[1] * 28;
      image.append(
        svg("line", {
          x1: 465,
          y1: 415,
          x2: x,
          y2: y,
          stroke: color,
          "stroke-width": 2,
        }),
      );
      const label = svg("text", {
        x: x + 3,
        y: y - 3,
        fill: color,
        "font-size": 13,
      });
      label.textContent = axis;
      image.append(label);
    }
    image.append(title);
    target.append(image);
    const legend = document.createElement("ol");
    geometry.facets.forEach((facet) => {
      const item = document.createElement("li");
      item.textContent = `${facet.facet_id} \u2014 source ${facet.part_id}; ${num(facet.area_fraction * 100)}% of source sheet area`;
      legend.append(item);
    });
    target.append(legend);
  }
  function show(result) {
    last = result;
    byId("stand-stage-label").textContent = result.selected_stage_label;
    byId("stand-status").textContent = result.stage_analysis
      ? `Explicit hypothetical stage: ${result.stage_analysis.reports.length} separate component reports. ${result.stage_analysis.blockers.join(" ")}`
      : result.report
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
      item.textContent = `${op.id} \u2014 ${clean(op.type)} \u2014 ${state}. Prerequisites: ${op.depends_on.join(", ") || "none"}. Planned attachment effects: ${op.attached_joint_ids.join(", ") || "none"}; detach effects: ${op.detached_joint_ids.join(", ") || "none"}.`;
      const description = document.createElement("p");
      description.textContent = `Existing manual: ${op.instruction} Tools: ${op.tools.join(", ")}.`;
      item.append(description);
      operations.append(item);
    });
    const metrics = byId("stand-result");
    metrics.replaceChildren();
    const reports =
      result.stage_analysis?.reports ?? (result.report ? [result.report] : []);
    reports.forEach((report, index) => {
      const heading = document.createElement("h3");
      heading.textContent = result.stage_analysis
        ? `Component ${index + 1}: ${(result.stage_analysis.component_part_ids[index] ?? []).join(", ")} \u2014 ${clean(report.status)}`
        : "Assembled stand checks";
      metrics.append(heading);
      for (const entry of report.results) {
        const p = document.createElement("p");
        p.textContent = `${entry.check_type}: ${clean(entry.status)}. ${entry.explanation}`;
        metrics.append(p);
      }
      for (const overlay of report.overlays) {
        const p = document.createElement("p");
        p.textContent = `Combined COM: (${num(overlay.center_of_mass.x * 1000)}, ${num(overlay.center_of_mass.y * 1000)}, ${num(overlay.center_of_mass.z * 1000)}) mm. Signed clearance: ${num(overlay.signed_margin_m * 1000)} mm. Restoring moment: ${num(overlay.restoring_moment_n_m)} N\u00b7m. Black point = combined COM; thick edge = governing support edge.`;
        metrics.append(p);
      }
    });
    if (result.stage_analysis) {
      const summary = document.createElement("p");
      summary.textContent = `Present: ${result.stage_analysis.present_part_ids.join(", ")}. Future: ${result.stage_analysis.future_part_ids.join(", ") || "none"}. Active joints: ${result.stage_analysis.active_joint_ids.join(", ") || "none"}. Numeric COM values above use the declared support frame; drawn overlays use world coordinates.`;
      metrics.append(summary);
    }
    draw();
    byId("stand-download").disabled = false;
  }
  async function inspect(loads = null, stageExample = false) {
    if (!plan) return;
    const own = ++revision;
    byId("run-stand").disabled = true;
    byId("stand-error").textContent = "";
    byId("stand-status").textContent =
      "Inspecting canonical plan\u2026 previous result is historical.";
    try {
      const response = await fetch("/inspect-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan,
          completed_prefix: Number(stage.value),
          loads,
          stage_example: stageExample,
          stage_snapshot:
            stageExample || !byId("stand-snapshot").value.trim()
              ? null
              : JSON.parse(byId("stand-snapshot").value),
        }),
        signal: AbortSignal.timeout(15000),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || "Plan inspection failed");
      if (own !== revision) return;
      if (stageExample)
        byId("stand-snapshot").value = JSON.stringify(
          result.request.stage_snapshot,
          null,
          2,
        );
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
    initial.textContent = "0 \u2014 planned target reference; no work assumed";
    stage.append(initial);
    plan.operations.forEach((op, i) => {
      const option = document.createElement("option");
      option.value = String(i + 1);
      option.textContent = `${i + 1} \u2014 ${clean(op.type)} (${op.id})`;
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
    byId("stand-snapshot").value = "";
    byId("stand-checks").value = "";
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
  stage.addEventListener("change", () => {
    byId("stand-snapshot").value = "";
    inspect();
  });
  byId("stand-stage-example").addEventListener("click", () => {
    stage.value = "1";
    inspect(null, true);
  });
  byId("run-stage-snapshot").addEventListener("click", () => inspect());
  document.querySelectorAll("[data-stand-view]").forEach((button) =>
    button.addEventListener("click", () => {
      const preset = button.dataset.standView;
      Object.assign(
        camera,
        preset === "front"
          ? { yaw: 0, elevation: 0, zoom: 1 }
          : preset === "side"
            ? { yaw: 90, elevation: 0, zoom: 1 }
            : { yaw: 315, elevation: 30, zoom: 1 },
      );
      redrawCamera();
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
  const quantity = (value, unit) => ({
    kind: "scalar",
    value,
    unit,
    provenance: "assumed",
    confirmed: false,
  });
  document.querySelectorAll("[data-check-example]").forEach((button) =>
    button.addEventListener("click", () => {
      if (!plan) return;
      const kind = button.dataset.checkExample;
      const joints = last?.selected_geometry?.attached_joint_ids ?? [];
      const checks =
        kind === "sliding"
          ? {
              sliding: {
                contact_id: "assumed-base-contact",
                normal_force_n: quantity(10, "N"),
                tangential_force_n: quantity(2, "N"),
                friction_coefficient: quantity(0.3, "1"),
                planar_coulomb_applicable: true,
              },
            }
          : kind === "joint"
            ? {
                joint_demands: joints.map((joint) => ({
                  joint_id: joint,
                  demand_n: quantity(2, "N"),
                  allowable_n: quantity(3, "N"),
                  capacity_basis: "Invented scalar example; not a tested joint",
                  scalar_mode_applicable: true,
                })),
              }
            : {
                deformation: {
                  member_id: plan.parts[0].id,
                  support_model: "cantilever_end_load",
                  force_n: quantity(1, "N"),
                  length_m: quantity(0.1, "m"),
                  elastic_modulus_pa: quantity(1e9, "Pa"),
                  second_moment_m4: quantity(1e-10, "m4"),
                  allowable_deflection_m: quantity(0.004, "m"),
                  linear_elastic_small_deflection_applicable: true,
                },
              };
      byId("stand-checks").value = JSON.stringify(checks, null, 2);
      changed();
      byId("stand-status").textContent =
        "Invented supplied-demand example loaded. Select an assembled stage, load or enter masses, then evaluate. This replaces other supplied-demand examples; missing checks remain unverified. An explicit snapshot uses its own component_loads instead.";
    }),
  );
  byId("clear-checks").addEventListener("click", () => {
    byId("stand-checks").value = "";
    changed();
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
    try {
      if (byId("stand-checks").value.trim())
        loads.case_checks = JSON.parse(byId("stand-checks").value);
      inspect(loads);
    } catch (error) {
      byId("stand-error").textContent = error.message;
    }
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
  viewport.addEventListener("pointerdown", (event) => {
    if (
      !event.target.closest("svg") ||
      (event.pointerType === "mouse" && event.button !== 0)
    )
      return;
    event.preventDefault();
    viewport.focus({ preventScroll: true });
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    const old = pointers.get(event.pointerId);
    if (!old) return;
    const before = [...pointers.values()];
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const after = [...pointers.values()];
    if (before.length === 2) {
      const oldDistance = Math.hypot(
        before[0].x - before[1].x,
        before[0].y - before[1].y,
      );
      const distance = Math.hypot(
        after[0].x - after[1].x,
        after[0].y - after[1].y,
      );
      if (oldDistance > 1) camera.zoom *= distance / oldDistance;
    } else if (before.length === 1) {
      const width =
        viewport.querySelector("svg")?.getBoundingClientRect().width || 520;
      camera.yaw += ((event.clientX - old.x) * 360) / width;
      camera.elevation += ((event.clientY - old.y) * 180) / width;
    }
    redrawCamera();
  });
  function releasePointer(event) {
    pointers.delete(event.pointerId);
    if (viewport.hasPointerCapture(event.pointerId))
      viewport.releasePointerCapture(event.pointerId);
    if (!pointers.size) viewport.classList.remove("dragging");
  }
  viewport.addEventListener("pointerup", releasePointer);
  viewport.addEventListener("pointercancel", releasePointer);
  viewport.addEventListener("lostpointercapture", (event) => {
    pointers.delete(event.pointerId);
    if (!pointers.size) viewport.classList.remove("dragging");
  });
  viewport.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 5 : 15;
    if (event.key === "ArrowLeft") camera.yaw -= step;
    else if (event.key === "ArrowRight") camera.yaw += step;
    else if (event.key === "ArrowUp") camera.elevation += step;
    else if (event.key === "ArrowDown") camera.elevation -= step;
    else if (event.key === "+" || event.key === "=") camera.zoom *= 1.1;
    else if (event.key === "-") camera.zoom /= 1.1;
    else if (event.key === "Home") {
      event.preventDefault();
      resetCamera();
      return;
    } else return;
    event.preventDefault();
    redrawCamera();
  });
  viewport.addEventListener(
    "wheel",
    (event) => {
      if (!event.target.closest("svg")) return;
      event.preventDefault();
      camera.zoom *= Math.exp(-clamp(event.deltaY, -100, 100) * 0.002);
      redrawCamera();
    },
    { passive: false },
  );
  byId("stand-zoom").addEventListener("input", (event) => {
    camera.zoom = Number(event.target.value);
    redrawCamera();
  });
  byId("stand-reset-camera").addEventListener("click", resetCamera);
  normalizeCamera();
  loadSample();
})();
