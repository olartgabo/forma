const form = document.getElementById("scenario");
const error = document.getElementById("error");
const status = document.getElementById("status");
const packet = document.getElementById("packet");
const run = document.getElementById("run");
const runJson = document.getElementById("run-json");
const download = document.getElementById("download");
let examples;
let last;
let revision = 0;
const expected = {
  centered:
    "Synthetic example: expect 50 mm clearance and 0.14715 N·m restoring moment. Only the static criterion can pass.",
  edge: "Synthetic example: expect combined y=50 mm, zero clearance and an indeterminate boundary result.",
  outside:
    "Synthetic example: expect combined y≈66.67 mm and negative clearance, so the static criterion fails.",
  unknown:
    "Synthetic example: device mass is unknown. Expect needs measurement and no calculated COM overlay.",
};
const clean = (word) => word.replaceAll("_", " ");
const number = (value) => Number(value.toPrecision(7)).toString();
function dirty() {
  revision++;
  if (last)
    status.textContent =
      "Inputs changed — displayed result is historical. Run again.";
}
form.addEventListener("input", () => {
  dirty();
  document.getElementById("expectation").textContent =
    "Edited hypothetical inputs. The original example's expected result no longer applies.";
});
packet.addEventListener("input", dirty);
function load(name) {
  for (const [key, value] of Object.entries(examples[name])) {
    const input = form.elements.namedItem(key);
    if (input.type === "checkbox") input.checked = value;
    else input.value = value ?? "";
  }
  dirty();
  document.getElementById("expectation").textContent = expected[name];
}
function svgElement(tag, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes))
    element.setAttribute(name, value);
  return element;
}
function draw(overlay) {
  const target = document.getElementById("diagram");
  target.replaceChildren();
  if (!overlay) return;
  const all = [
    ...overlay.support_polygon,
    overlay.center_of_mass,
    ...overlay.critical_edge,
  ];
  const minX = Math.min(...all.map((p) => p.x));
  const minY = Math.min(...all.map((p) => p.y));
  const span = Math.max(
    Math.max(...all.map((p) => p.x)) - minX,
    Math.max(...all.map((p) => p.y)) - minY,
    0.001,
  );
  const scale = 300 / span;
  const xy = (p) => [40 + (p.x - minX) * scale, 340 - (p.y - minY) * scale];
  if (all.some((p) => xy(p).some((v) => !Number.isFinite(v)))) {
    target.textContent =
      "Coordinates cannot be displayed at this numeric scale; inspect the report JSON.";
    return;
  }
  const svg = svgElement("svg", {
    viewBox: "0 0 400 390",
    role: "img",
    "aria-label":
      "Top view: support outline, combined COM point and critical edge",
  });
  svg.append(
    svgElement("polygon", {
      points: overlay.support_polygon.map((p) => xy(p).join(",")).join(" "),
      fill: "#e5eee9",
      stroke: "#164d40",
      "stroke-width": 2,
    }),
  );
  svg.append(
    svgElement("polyline", {
      points: overlay.critical_edge.map((p) => xy(p).join(",")).join(" "),
      fill: "none",
      stroke: "#a15c00",
      "stroke-width": 5,
    }),
  );
  const [cx, cy] = xy(overlay.center_of_mass);
  svg.append(svgElement("circle", { cx, cy, r: 6, fill: "#172b36" }));
  const title = svgElement("text", { x: 12, y: 22, fill: "#172b36" });
  title.textContent = "COM ● · support outline · critical edge (thick)";
  svg.append(title);
  target.append(svg);
  const caption = document.createElement("p");
  caption.textContent = `Combined COM (mm): x ${number(overlay.center_of_mass.x * 1000)}, y ${number(overlay.center_of_mass.y * 1000)}, z ${number(overlay.center_of_mass.z * 1000)}. Signed clearance ${number(overlay.signed_margin_m * 1000)} mm. Restoring moment ${number(overlay.restoring_moment_n_m)} N·m.`;
  target.append(caption);
}
async function calculate(path, value) {
  const ownRevision = revision;
  run.disabled = runJson.disabled = true;
  error.textContent = "";
  status.textContent = "Calculating… previous result is historical.";
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Calculation failed");
    if (revision !== ownRevision) {
      status.textContent =
        "Inputs changed while calculating. Run again for the current inputs.";
      return;
    }
    last = result;
    packet.value = JSON.stringify(
      { input: result.input, policy: result.policy },
      null,
      2,
    );
    document.getElementById("report").textContent = JSON.stringify(
      result.report,
      null,
      2,
    );
    status.textContent = `Modeled result: ${clean(result.report.status)}. Coverage: ${clean(result.report.coverage)}.`;
    const list = document.createElement("ul");
    for (const check of result.report.results) {
      const item = document.createElement("li");
      item.textContent = `${check.case_id} / ${check.check_type}: ${clean(check.status)}. ${check.explanation}`;
      list.append(item);
    }
    document.getElementById("results").replaceChildren(list);
    draw(result.report.overlays[0]);
    download.disabled = false;
  } catch (e) {
    error.textContent = e.message;
    status.textContent = last
      ? "Calculation failed. Displayed result is historical."
      : "No successful calculation.";
  } finally {
    run.disabled = runJson.disabled = false;
  }
}
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = {};
  for (const input of form.querySelectorAll("input"))
    value[input.name] =
      input.type === "checkbox"
        ? input.checked
        : input.value === ""
          ? null
          : Number(input.value);
  calculate("/evaluate", value);
});
runJson.addEventListener("click", () => {
  try {
    calculate("/evaluate-input", JSON.parse(packet.value));
  } catch (e) {
    error.textContent = `Invalid JSON: ${e.message}`;
  }
});
download.addEventListener("click", () => {
  if (!last) return;
  const value = { ...last, feedback: document.getElementById("notes").value };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "forma-engine-feedback.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
fetch("/presets")
  .then((response) => {
    if (!response.ok) throw new Error("Could not load the synthetic examples");
    return response.json();
  })
  .then((value) => {
    examples = value;
    document
      .querySelectorAll("[data-preset]")
      .forEach((button) =>
        button.addEventListener("click", () => load(button.dataset.preset)),
      );
    load("centered");
  })
  .catch((e) => {
    error.textContent = e.message;
  });
