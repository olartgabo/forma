/** Extract only saved engine part graphics into a fitted, isolated thumbnail.
 * The original manual remains unchanged. No source DOM node is inserted.
 */
export function savedDrawingThumbnail(source: string): string | null {
  if (
    !source ||
    source.length > 2_000_000 ||
    /<!DOCTYPE|<!ENTITY/i.test(source)
  )
    return null;
  const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
  const original = parsed.documentElement;
  if (original.localName !== "svg" || parsed.querySelector("parsererror"))
    return null;
  const ns = "http://www.w3.org/2000/svg";
  const output = document.createElementNS(ns, "svg");
  const primitives = new Set([
    "line",
    "path",
    "polygon",
    "polyline",
    "rect",
    "circle",
    "ellipse",
  ]);
  const numbers = /^[\s,0-9eE+.\-]+$/;
  const coordinates = new Set([
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "width",
    "height",
    "points",
  ]);
  let visited = 0;
  let shapes = 0;
  let invalid = false;
  function copy(
    node: Element,
    selected: boolean,
    depth: number,
  ): SVGElement | null {
    if (++visited > 4096 || depth > 32) {
      invalid = true;
      return null;
    }
    if (node.namespaceURI !== ns || node.hasAttribute("data-joint-id"))
      return null;
    const tag = node.localName;
    if (tag !== "svg" && tag !== "g" && !primitives.has(tag)) return null;
    const included =
      selected ||
      node.hasAttribute("data-part-id") ||
      node.hasAttribute("data-feature-id");
    const target = document.createElementNS(ns, tag === "svg" ? "g" : tag);
    const transform = node.getAttribute("transform");
    if (transform) {
      // Only numeric SVG transforms, never CSS, references or arbitrary tokens.
      if (
        !/^(\s*(matrix|translate|scale|rotate|skewX|skewY)\([\s,0-9eE+.\-]+\)\s*)+$/.test(
          transform,
        )
      ) {
        invalid = true;
        return null;
      }
      target.setAttribute("transform", transform);
    }
    if (primitives.has(tag)) {
      if (!included) return null;
      for (const attribute of Array.from(node.attributes)) {
        if (coordinates.has(attribute.name)) {
          if (
            !numbers.test(attribute.value) ||
            attribute.value.length > 32768
          ) {
            invalid = true;
            return null;
          }
          target.setAttribute(attribute.name, attribute.value);
        }
      }
      if (tag === "path") {
        const d = node.getAttribute("d");
        if (
          !d ||
          d.length > 65536 ||
          !/^[MmZzLlHhVvCcSsQqTtAa0-9eE+.\s,\-]+$/.test(d)
        ) {
          invalid = true;
          return null;
        }
        target.setAttribute("d", d);
      }
      target.setAttribute("fill", "none");
      target.setAttribute("stroke", "#49d8ed");
      target.setAttribute("stroke-width", "2.5");
      target.setAttribute("stroke-linejoin", "round");
      target.setAttribute("stroke-linecap", "round");
      target.setAttribute("vector-effect", "non-scaling-stroke");
      shapes++;
      return target;
    }
    for (const child of Array.from(node.children)) {
      const clean = copy(child, included, depth + 1);
      if (clean) target.appendChild(clean);
    }
    return target.children.length ? target : null;
  }
  const graphics = copy(original, false, 0);
  if (!graphics || invalid || !shapes) return null;
  output.appendChild(graphics);
  output.setAttribute("width", "360");
  output.setAttribute("height", "240");
  output.setAttribute("preserveAspectRatio", "xMidYMid meet");
  output.style.position = "fixed";
  output.style.left = "-10000px";
  output.style.visibility = "hidden";
  output.style.pointerEvents = "none";
  document.body.appendChild(output);
  try {
    const box = (graphics as SVGGraphicsElement).getBBox();
    if (
      ![box.x, box.y, box.width, box.height].every(Number.isFinite) ||
      box.width <= 0 ||
      box.height <= 0
    )
      return null;
    const padding = Math.max(box.width, box.height) * 0.12;
    output.setAttribute(
      "viewBox",
      `${box.x - padding} ${box.y - padding} ${box.width + padding * 2} ${box.height + padding * 2}`,
    );
    output.removeAttribute("style");
    return new XMLSerializer().serializeToString(output);
  } catch {
    return null;
  } finally {
    output.remove();
  }
}
