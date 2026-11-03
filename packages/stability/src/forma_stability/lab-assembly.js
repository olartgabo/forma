/* Friendly authoring only: all geometry, centroids and checks come from Python. */
(() => {
  const $ = (id) => document.getElementById(id);
  let editor = {
    panels: [],
    stages: [{ id: "stage-1", label: "Lay out the parts" }],
    joints: [],
    required_margin_mm: 0,
  };
  let current = 0,
    selected = 0,
    revision = 0,
    last = null;
  const camera = { yaw: 315, pitch: 30, zoom: 1 };
  const pointers = new Map();
  let frame;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const node = (tag, text, attrs = {}) => {
    const n = document.createElement(tag);
    if (text) n.textContent = text;
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const svg = (tag, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  function stale() {
    revision++;
    $("assembly-status").textContent = last
      ? "Changed inputs. The displayed model and results are from the previous evaluation."
      : "Ready to evaluate your hypothetical assembly.";
    $("assembly-json").value = JSON.stringify(editor, null, 2);
  }
  function field(parent, title, value, change, type = "number") {
    const label = node("label", title);
    const input = node("input", null, { type });
    input.value = value ?? "";
    if (type === "number") input.step = "any";
    input.addEventListener("change", () => {
      change(
        type === "number"
          ? input.value === ""
            ? null
            : Number(input.value)
          : input.value,
      );
      stale();
    });
    label.append(input);
    parent.append(label);
    return input;
  }
  function check(parent, title, value, change) {
    const label = node("label", null, { class: "check" });
    const input = node("input", null, { type: "checkbox" });
    input.checked = value;
    input.addEventListener("change", () => {
      change(input.checked);
      stale();
    });
    label.append(input, document.createTextNode(title));
    parent.append(label);
  }
  function choose(parent, title, values, value, change) {
    const label = node("label", title);
    const select = node("select");
    for (const [id, name] of values) {
      const option = node("option", name, { value: id });
      select.append(option);
    }
    select.value = String(value);
    select.addEventListener("change", () => {
      change(select.value);
      stale();
    });
    label.append(select);
    parent.append(label);
    return select;
  }
  function render() {
    $("assembly-margin").value = String(editor.required_margin_mm);
    const chips = $("assembly-stages");
    chips.replaceChildren();
    editor.stages.forEach((stage, i) => {
      const button = node("button", `${i + 1}. ${stage.label}`, {
        type: "button",
        "aria-current": i === current ? "step" : "false",
      });
      button.addEventListener("click", () => selectStage(i));
      chips.append(button);
    });
    $("assembly-step-count").textContent =
      `STEP ${current + 1} / ${editor.stages.length}`;
    $("assembly-step-title").textContent = editor.stages[current].label;
    $("assembly-stage-name").value = editor.stages[current].label;
    $("assembly-prev").disabled = current === 0;
    $("assembly-next").disabled = current === editor.stages.length - 1;
    const list = $("assembly-panel");
    list.replaceChildren();
    editor.panels.forEach((p, i) =>
      list.append(node("option", p.label, { value: i })),
    );
    selected = Math.min(selected, Math.max(0, editor.panels.length - 1));
    list.value = String(selected);
    renderPanel();
    renderJoints();
    $("assembly-json").value = JSON.stringify(editor, null, 2);
  }
  function selectStage(index) {
    current = index;
    stale();
    render();
    if (editor.panels.length) evaluate();
  }
  function stateFor(panel) {
    return panel.states.find((s) => s.stage_id === editor.stages[current].id);
  }
  function renderPanel() {
    const target = $("assembly-panel-editor");
    target.replaceChildren();
    const panel = editor.panels[selected];
    if (!panel) {
      target.append(
        node(
          "p",
          "Add a panel to begin. Its mass stays unknown until you enter it.",
        ),
      );
      return;
    }
    field(
      target,
      "Panel name",
      panel.label,
      (v) => {
        panel.label = v;
        render();
      },
      "text",
    );
    choose(
      target,
      "Present from stage",
      editor.stages.map((s, i) => [i, `${i + 1}. ${s.label}`]),
      panel.first_stage,
      (v) => {
        panel.first_stage = Number(v);
        renderPanel();
      },
    );
    field(
      target,
      "Mass (g) — blank means unknown",
      panel.mass_g,
      (v) => (panel.mass_g = v),
    );
    target.append(node("h4", "Shape in its local plane"));
    const dims = node("div", null, { class: "editor-grid two" });
    let width =
        Math.max(...panel.vertices_mm.map((p) => p[0])) -
        Math.min(...panel.vertices_mm.map((p) => p[0])),
      height =
        Math.max(...panel.vertices_mm.map((p) => p[1])) -
        Math.min(...panel.vertices_mm.map((p) => p[1]));
    field(dims, "Width (mm)", width, (v) => (width = v));
    field(dims, "Depth (mm)", height, (v) => (height = v));
    target.append(dims);
    const rectangle = node("button", "Use rectangle dimensions", {
      type: "button",
    });
    rectangle.addEventListener("click", () => {
      panel.vertices_mm = [
        [-width / 2, -height / 2],
        [width / 2, -height / 2],
        [width / 2, height / 2],
        [-width / 2, height / 2],
      ];
      stale();
      renderPanel();
    });
    target.append(rectangle);
    const label = node(
      "label",
      "Polygon corners (x, y in mm; one corner per line)",
    );
    const vertices = node("textarea", null, { rows: 4 });
    vertices.value = panel.vertices_mm.map((p) => p.join(", ")).join("\n");
    vertices.addEventListener("change", () => {
      try {
        const points = vertices.value
          .trim()
          .split(/\n/)
          .map((line) =>
            line
              .trim()
              .split(/[,\s]+/)
              .map(Number),
          );
        if (
          points.some(
            (p) => p.length !== 2 || p.some((v) => !Number.isFinite(v)),
          )
        )
          throw Error("Enter two finite coordinates per corner.");
        panel.vertices_mm = points;
        $("assembly-error").textContent = "";
        stale();
      } catch (error) {
        $("assembly-error").textContent = error.message;
      }
    });
    label.append(vertices);
    target.append(label);
    check(
      target,
      "Assume uniform sheet mass (centroid calculated by engine)",
      panel.uniform_sheet_assumed,
      (v) => (panel.uniform_sheet_assumed = v),
    );
    const state = stateFor(panel);
    target.append(node("h4", `Pose at ${editor.stages[current].label}`));
    if (current < panel.first_stage) {
      target.append(
        node("p", "Future panel: excluded from this stage physics."),
      );
      return;
    }
    if (!state) {
      const button = node("button", "Declare pose for this stage", {
        type: "button",
      });
      button.addEventListener("click", () => {
        panel.states.push(newState(editor.stages[current].id));
        stale();
        renderPanel();
      });
      target.append(button);
      return;
    }
    for (const [key, title] of [
      ["translation_mm", "Position (mm)"],
      ["rotation_deg", "Physical rotation (degrees)"],
    ]) {
      target.append(node("p", title));
      const row = node("div", null, { class: "editor-grid" });
      ["X", "Y", "Z"].forEach((axis, i) =>
        field(row, axis, state[key][i], (v) => (state[key][i] = v)),
      );
      target.append(row);
    }
    check(
      target,
      "Assume this full face contacts the table",
      state.full_face_contact_assumed,
      (v) => (state.full_face_contact_assumed = v),
    );
    check(
      target,
      "Assume this panel behaves as a rigid body",
      state.rigid_body_assumed,
      (v) => (state.rigid_body_assumed = v),
    );
    target.append(
      node(
        "p",
        "Physical rotations apply X, then Y, then Z. New panels start with explicitly listed zero poses in this and later stages. Camera movement only changes your view.",
        { class: "muted" },
      ),
    );
  }
  function renderJoints() {
    const target = $("assembly-joints");
    target.replaceChildren();
    editor.joints.forEach((joint, index) => {
      const group = node("fieldset");
      group.append(node("legend", joint.id));
      const options = editor.panels.map((p) => [p.id, p.label]);
      choose(
        group,
        "First panel",
        options,
        joint.first_panel_id,
        (v) => (joint.first_panel_id = v),
      );
      field(
        group,
        "First edge (starts at 0)",
        joint.first_edge,
        (v) => (joint.first_edge = v),
      );
      choose(
        group,
        "Second panel",
        options,
        joint.second_panel_id,
        (v) => (joint.second_panel_id = v),
      );
      field(
        group,
        "Second edge (starts at 0)",
        joint.second_edge,
        (v) => (joint.second_edge = v),
      );
      choose(
        group,
        "Active from stage",
        editor.stages.map((s, i) => [i, s.label]),
        joint.first_stage,
        (v) => (joint.first_stage = Number(v)),
      );
      check(
        group,
        "Assume joint is rigid",
        joint.rigid_assumed,
        (v) => (joint.rigid_assumed = v),
      );
      const remove = node("button", "Remove joint", { type: "button" });
      remove.addEventListener("click", () => {
        editor.joints.splice(index, 1);
        stale();
        renderJoints();
      });
      group.append(remove);
      target.append(group);
    });
  }
  const newState = (stage_id) => ({
    stage_id,
    translation_mm: [0, 0, 0],
    rotation_deg: [0, 0, 0],
    full_face_contact_assumed: false,
    rigid_body_assumed: false,
  });
  $("assembly-add-panel").addEventListener("click", () => {
    if (editor.panels.length >= 16) return;
    let id;
    do {
      id = `panel-${++revision}`;
    } while (editor.panels.some((p) => p.id === id));
    editor.panels.push({
      id,
      label: `Panel ${editor.panels.length + 1}`,
      vertices_mm: [
        [-50, -50],
        [50, -50],
        [50, 50],
        [-50, 50],
      ],
      mass_g: null,
      uniform_sheet_assumed: false,
      first_stage: current,
      states: editor.stages.slice(current).map((s) => newState(s.id)),
    });
    selected = editor.panels.length - 1;
    stale();
    render();
  });
  $("assembly-add-stage").textContent = "Copy previous into new stage";
  $("assembly-add-stage").addEventListener("click", () => {
    if (editor.stages.length >= 64) return;
    const previous = editor.stages.at(-1);
    const stage = {
      id: `stage-${editor.stages.length + 1}`,
      label: `Construction step ${editor.stages.length + 1}`,
    };
    editor.stages.push(stage);
    for (const panel of editor.panels) {
      const old = panel.states.find((s) => s.stage_id === previous.id);
      if (old) panel.states.push({ ...clone(old), stage_id: stage.id });
    }
    current = editor.stages.length - 1;
    stale();
    render();
  });
  $("assembly-add-joint").addEventListener("click", () => {
    if (editor.panels.length < 2) {
      $("assembly-error").textContent =
        "Add at least two panels before declaring a joint.";
      return;
    }
    editor.joints.push({
      id: `joint-${++revision}`,
      first_panel_id: editor.panels[0].id,
      first_edge: 0,
      second_panel_id: editor.panels[1].id,
      second_edge: 0,
      first_stage: current,
      rigid_assumed: false,
    });
    stale();
    renderJoints();
  });
  $("assembly-panel").addEventListener("change", (e) => {
    selected = Number(e.target.value);
    renderPanel();
  });
  $("assembly-stage-name").addEventListener("change", (e) => {
    editor.stages[current].label = e.target.value;
    stale();
    render();
  });
  $("assembly-margin").addEventListener("change", (e) => {
    editor.required_margin_mm = Number(e.target.value);
    stale();
  });
  $("assembly-prev").addEventListener("click", () => selectStage(current - 1));
  $("assembly-next").addEventListener("click", () => selectStage(current + 1));
  $("assembly-new").addEventListener("click", () => {
    editor = {
      panels: [],
      stages: [{ id: "stage-1", label: "Lay out the parts" }],
      joints: [],
      required_margin_mm: 0,
    };
    current = selected = 0;
    last = null;
    stale();
    render();
    draw();
    $("assembly-results").replaceChildren();
  });
  async function evaluate() {
    const own = ++revision;
    $("assembly-evaluate").disabled = true;
    $("assembly-error").textContent = "";
    $("assembly-status").textContent = "Evaluating the declared stage...";
    try {
      const response = await fetch("/evaluate-assembly", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ editor, stage_index: current }),
        signal: AbortSignal.timeout(15000),
      });
      const payload = await response.json();
      if (!response.ok) throw Error(payload.error || "Evaluation failed");
      if (own !== revision) return;
      last = payload;
      $("assembly-report").textContent = JSON.stringify(payload, null, 2);
      show();
    } catch (error) {
      if (own === revision) {
        $("assembly-error").textContent = error.message;
        $("assembly-status").textContent =
          "Could not evaluate. Any previous model and result are historical.";
      }
    } finally {
      $("assembly-evaluate").disabled = false;
    }
  }
  $("assembly-evaluate").addEventListener("click", evaluate);
  function result() {
    return last?.result ?? last?.analysis ?? last;
  }
  function show() {
    const data = result();
    const reports = data.reports ?? [];
    $("assembly-status").textContent =
      `${reports.length} separate component report${reports.length === 1 ? "" : "s"} for this hypothetical stage. ${data.blockers?.join(" ") ?? ""}`;
    const target = $("assembly-results");
    target.replaceChildren();
    target.append(
      node(
        "p",
        `Future panels excluded from physics: ${(data.future_part_ids ?? []).map((id) => last.editor?.panels.find((p) => p.id === id)?.label ?? id).join(", ") || "none"}.`,
      ),
    );
    reports.forEach((report, index) => {
      const card = node("details");
      card.append(
        node(
          "summary",
          `Component ${index + 1}: ${report.status.replaceAll("_", " ")}`,
        ),
      );
      for (const item of report.results)
        card.append(
          node(
            "p",
            `${item.check_type}: ${item.status.replaceAll("_", " ")}. ${item.explanation}`,
          ),
        );
      target.append(card);
    });
    draw();
  }
  function draw() {
    const viewport = $("assembly-view");
    viewport.replaceChildren();
    const data = result();
    const facets = data?.facets ?? [];
    if (!facets.length) {
      viewport.append(
        node("p", "No evaluated geometry. Add panels and evaluate this stage."),
      );
      return;
    }
    const points = facets.flatMap((f) => f.vertices);
    const axes = ["x", "y", "z"];
    const low = axes.map((a) => Math.min(...points.map((p) => p[a]))),
      high = axes.map((a) => Math.max(...points.map((p) => p[a])));
    const center = low.map((v, i) => v / 2 + high[i] / 2);
    const radius = Math.max(
      0.0005,
      Math.hypot(...low.map((v, i) => (high[i] - v) / 2)),
    );
    const yaw = (camera.yaw * Math.PI) / 180,
      pitch = (camera.pitch * Math.PI) / 180;
    const project = (p) => {
      const [x, y, z] = axes.map((a, i) => p[a] - center[i]);
      const h = -Math.sin(yaw) * x + Math.cos(yaw) * y;
      return [
        Math.cos(yaw) * x + Math.sin(yaw) * y,
        Math.sin(pitch) * h - Math.cos(pitch) * z,
        Math.cos(pitch) * h + Math.sin(pitch) * z,
      ];
    };
    const xy = (p) => {
      const q = project(p);
      return [
        320 + (q[0] * 230 * camera.zoom) / radius,
        250 + (q[1] * 230 * camera.zoom) / radius,
      ];
    };
    if (
      !Number.isFinite(radius) ||
      points.some((p) => xy(p).some((v) => !Number.isFinite(v)))
    ) {
      viewport.append(
        node("p", "Geometry exceeds the display scale; inspect exact results."),
      );
      return;
    }
    const image = svg("svg", {
      viewBox: "0 0 640 500",
      role: "img",
      "aria-label": "Evaluated assembly geometry; camera rotation only",
    });
    const colors = ["#8fb9a8", "#e7c48a", "#adc3dc", "#c5b2d6", "#e3b4a5"];
    facets
      .map((f, i) => ({ f, i, depth: project(f.centroid)[2] }))
      .sort((a, b) => a.depth - b.depth)
      .forEach(({ f, i }) => {
        image.append(
          svg("polygon", {
            points: f.vertices.map((p) => xy(p).join(",")).join(" "),
            fill: colors[i % colors.length],
            "fill-opacity": ".8",
            stroke: "#36574b",
            "stroke-width": 1.5,
            "data-facet-id": f.facet_id,
          }),
        );
        const at = xy(f.centroid);
        const label = svg("text", {
          x: at[0],
          y: at[1],
          "text-anchor": "middle",
          fill: "#183e31",
          "font-size": 14,
        });
        label.textContent =
          last.editor?.panels.find((p) => p.id === f.part_id)?.label ??
          f.part_id;
        image.append(label);
      });
    viewport.append(image);
  }
  function cameraDraw() {
    camera.yaw = ((camera.yaw % 360) + 360) % 360;
    camera.pitch = Math.max(-85, Math.min(85, camera.pitch));
    camera.zoom = Math.max(0.4, Math.min(3, camera.zoom));
    $("assembly-zoom").value = String(camera.zoom);
    $("assembly-camera-state").textContent =
      `View ${Math.round(camera.yaw)} degrees / ${Math.round(camera.pitch)} degrees. Zoom ${camera.zoom.toFixed(2)}x. Display only.`;
    $("assembly-view").dataset.yaw = String(camera.yaw);
    if (!frame)
      frame = requestAnimationFrame(() => {
        frame = null;
        draw();
      });
  }
  const viewport = $("assembly-view");
  viewport.addEventListener("pointerdown", (e) => {
    if (
      !e.target.closest("svg") ||
      (e.pointerType === "mouse" && e.button !== 0)
    )
      return;
    e.preventDefault();
    viewport.focus({ preventScroll: true });
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    viewport.setPointerCapture(e.pointerId);
    viewport.classList.add("dragging");
  });
  viewport.addEventListener("pointermove", (e) => {
    const old = pointers.get(e.pointerId);
    if (!old) return;
    const before = [...pointers.values()];
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (before.length === 2) {
      const after = [...pointers.values()],
        a = Math.hypot(before[0].x - before[1].x, before[0].y - before[1].y),
        b = Math.hypot(after[0].x - after[1].x, after[0].y - after[1].y);
      if (a > 1) camera.zoom *= b / a;
    } else {
      const w = viewport.clientWidth;
      camera.yaw += ((e.clientX - old.x) * 360) / w;
      camera.pitch += ((e.clientY - old.y) * 180) / w;
    }
    cameraDraw();
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"])
    viewport.addEventListener(name, (e) => {
      pointers.delete(e.pointerId);
      if (!pointers.size) viewport.classList.remove("dragging");
    });
  viewport.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") camera.yaw += 15;
    else if (e.key === "ArrowLeft") camera.yaw -= 15;
    else if (e.key === "ArrowUp") camera.pitch += 15;
    else if (e.key === "ArrowDown") camera.pitch -= 15;
    else if (e.key === "+" || e.key === "=") camera.zoom *= 1.1;
    else if (e.key === "-") camera.zoom /= 1.1;
    else if (e.key === "Home")
      Object.assign(camera, { yaw: 315, pitch: 30, zoom: 1 });
    else return;
    e.preventDefault();
    cameraDraw();
  });
  $("assembly-zoom").addEventListener("input", (e) => {
    camera.zoom = Number(e.target.value);
    cameraDraw();
  });
  $("assembly-reset-camera").addEventListener("click", () => {
    Object.assign(camera, { yaw: 315, pitch: 30, zoom: 1 });
    cameraDraw();
  });
  $("assembly-import").addEventListener("click", () => {
    try {
      const imported = JSON.parse($("assembly-json").value);
      const hasDraft = imported.draft_editor !== undefined;
      const next = hasDraft
        ? imported.draft_editor
        : (imported.editor ?? imported);
      const nextStage = hasDraft
        ? imported.draft_stage_index
        : (imported.stage_index ?? 0);
      if (
        !next ||
        !Array.isArray(next.panels) ||
        !Array.isArray(next.stages) ||
        !next.stages.length ||
        !Array.isArray(next.joints)
      )
        throw Error("Provide an editor with panels, stages and joints.");
      if (
        !Number.isInteger(nextStage) ||
        nextStage < 0 ||
        nextStage >= next.stages.length
      )
        throw Error("Imported stage index must identify an existing stage.");
      editor = next;
      current = nextStage;
      selected = 0;
      last = null;
      stale();
      render();
      draw();
      $("assembly-results").replaceChildren();
      $("assembly-report").textContent =
        "No calculation for imported draft. Evaluate this stage.";
      $("assembly-status").textContent =
        "Draft imported. Previous results are not current; evaluate this stage.";
      $("assembly-error").textContent = "";
    } catch (error) {
      $("assembly-error").textContent = error.message;
    }
  });
  $("assembly-export").addEventListener("click", () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            last
              ? {
                  ...last,
                  draft_editor: clone(editor),
                  draft_stage_index: current,
                }
              : { editor: clone(editor), stage_index: current },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const a = node("a", null, {
      href: url,
      download: "forma-assembly-experiment.json",
    });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  function example(kind) {
    const stages = [
      { id: "stage-1", label: "First panel on the table" },
      { id: "stage-2", label: "Add a second shape" },
      { id: "stage-3", label: "Add the third shape" },
    ];
    const shapes =
      kind === "polygons"
        ? [
            [
              [-60, -45],
              [60, -45],
              [0, 65],
            ],
            [
              [-45, -45],
              [45, -45],
              [45, 45],
              [-45, 45],
            ],
            [
              [-55, 0],
              [-25, -45],
              [25, -45],
              [55, 0],
              [25, 45],
              [-25, 45],
            ],
          ]
        : [
            [
              [-90, -55],
              [90, -55],
              [90, 55],
              [-90, 55],
            ],
            [
              [-60, -30],
              [60, -30],
              [60, 30],
              [-60, 30],
            ],
            [
              [-35, -35],
              [35, -35],
              [35, 35],
              [-35, 35],
            ],
          ];
    editor = {
      stages,
      joints: [],
      required_margin_mm: 0,
      panels: shapes.map((vertices_mm, i) => ({
        id: `example-panel-${i + 1}`,
        label:
          kind === "polygons"
            ? ["Triangle", "Square", "Hexagon"][i]
            : ["Base panel", "Long panel", "Small panel"][i],
        vertices_mm,
        mass_g: 20 + 10 * i,
        uniform_sheet_assumed: true,
        first_stage: i,
        states: stages.slice(i).map((stage) => ({
          ...newState(stage.id),
          translation_mm: [(i - 1) * 170, 0, 0],
          full_face_contact_assumed: true,
          rigid_body_assumed: true,
        })),
      })),
    };
    current = selected = 0;
    last = null;
    stale();
    render();
    evaluate();
  }
  for (const [kind, title] of [
    ["polygons", "Hypothetical polygon panels"],
    ["rectangles", "Hypothetical rectangle panels"],
  ]) {
    const button = node("button", title, { type: "button" });
    button.addEventListener("click", () => example(kind));
    $("assembly-examples").append(button);
  }
  render();
  cameraDraw();
  example("polygons");
})();
