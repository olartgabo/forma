import type { CanonicalFacet, Point3 } from "./generated/contracts";

export type EnginePreviewGeometry = {
  readonly facets: ReadonlyArray<
    Pick<CanonicalFacet, "facet_id" | "part_id" | "vertices">
  >;
};

export type ProjectedFacet = {
  facetId: string;
  partId: string;
  points: string;
  depth: number;
  light: number;
};

const WIDTH = 360;
const HEIGHT = 240;
const MARGIN = 24;
const ROOT3 = Math.sqrt(3);
const dot = (a: Point3, b: Point3) => a.x * b.x + a.y * b.y + a.z * b.z;
const camera = { x: 0.3 * ROOT3, y: -0.4 * ROOT3, z: 0.5 };
const light = { x: -0.3, y: -0.4, z: Math.sqrt(0.75) };

/** A bounded orthographic capture of canonical surfaces, without added thickness.
 * Painter ordering handles separated faces; intersecting polygons are not split.
 */
export function projectEngineModel(
  geometry: EnginePreviewGeometry,
): ProjectedFacet[] | null {
  const facets = geometry?.facets;
  if (!Array.isArray(facets) || !facets.length || facets.length > 128)
    return null;
  let vertexCount = 0;
  const ids = new Set<string>();
  const low = { x: Infinity, y: Infinity, z: Infinity };
  const high = { x: -Infinity, y: -Infinity, z: -Infinity };
  for (const facet of facets) {
    if (
      !facet ||
      typeof facet.facet_id !== "string" ||
      typeof facet.part_id !== "string" ||
      !facet.facet_id ||
      !facet.part_id ||
      facet.facet_id.length > 256 ||
      facet.part_id.length > 256 ||
      ids.has(facet.facet_id) ||
      !Array.isArray(facet.vertices) ||
      facet.vertices.length < 3 ||
      facet.vertices.length > 256
    )
      return null;
    ids.add(facet.facet_id);
    vertexCount += facet.vertices.length;
    if (vertexCount > 8192) return null;
    for (const point of facet.vertices) {
      if (!point) return null;
      for (const axis of ["x", "y", "z"] as const) {
        const value = point[axis];
        if (!Number.isFinite(value) || Math.abs(value) > 1e6) return null;
        low[axis] = Math.min(low[axis], value);
        high[axis] = Math.max(high[axis], value);
      }
    }
  }
  // Center before projection to avoid cancellation at large translated origins.
  const center = {
    x: (low.x + high.x) / 2,
    y: (low.y + high.y) / 2,
    z: (low.z + high.z) / 2,
  };
  const extent = Math.max(high.x - low.x, high.y - low.y, high.z - low.z);
  if (extent <= 1e-12) return null;
  const normalize = (p: Point3): Point3 => ({
    x: (p.x - center.x) / extent,
    y: (p.y - center.y) / extent,
    z: (p.z - center.z) / extent,
  });
  const projected = [];
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;
  for (const facet of facets) {
    const vertices: Point3[] = facet.vertices.map(normalize);
    const normal = { x: 0, y: 0, z: 0 };
    // Newell's normal works for triangles and planar concave polygon outlines.
    for (let i = 0; i < vertices.length; i++) {
      const a = vertices[i],
        b = vertices[(i + 1) % vertices.length];
      normal.x += (a.y - b.y) * (a.z + b.z);
      normal.y += (a.z - b.z) * (a.x + b.x);
      normal.z += (a.x - b.x) * (a.y + b.y);
    }
    const length = Math.hypot(normal.x, normal.y, normal.z);
    if (length <= 1e-12) return null;
    const facing = dot(normal, camera) < 0 ? -1 : 1;
    const illumination = Math.max(0, (facing * dot(normal, light)) / length);
    const points = vertices.map((p) => {
      const x = 0.8 * p.x + 0.6 * p.y;
      const y = 0.3 * p.x - 0.4 * p.y - ROOT3 * 0.5 * p.z;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      return { x, y };
    });
    projected.push({
      facetId: facet.facet_id,
      partId: facet.part_id,
      points,
      light: illumination,
      depth:
        vertices.reduce((sum, p) => sum + dot(p, camera), 0) / vertices.length,
    });
  }
  const spanX = maxX - minX,
    spanY = maxY - minY;
  if (Math.max(spanX, spanY) <= 1e-12) return null;
  const scale = Math.min(
    (WIDTH - 2 * MARGIN) / Math.max(spanX, 1e-12),
    (HEIGHT - 2 * MARGIN) / Math.max(spanY, 1e-12),
  );
  const midX = (minX + maxX) / 2,
    midY = (minY + maxY) / 2;
  return projected
    .sort((a, b) => a.depth - b.depth || a.facetId.localeCompare(b.facetId))
    .map((facet) => ({
      ...facet,
      points: facet.points
        .map(
          (p) =>
            `${((p.x - midX) * scale + WIDTH / 2).toFixed(3)},${((p.y - midY) * scale + HEIGHT / 2).toFixed(3)}`,
        )
        .join(" "),
    }));
}
