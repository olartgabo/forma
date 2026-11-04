import type { CanonicalFacet, Point3 } from "./generated/contracts";

export type ProjectionPoint = { x: number; y: number; depth: number };
export type ConstructionView = "top" | "front" | "side";
const finitePoint = (point: Point3) =>
  [point.x, point.y, point.z].every(Number.isFinite);

/** Depth increases toward the viewer (screen-right cross screen-up).
 * Ascending painter order therefore draws the farthest facets first. */
export function constructionCamera(yawDegrees: number, pitchDegrees: number) {
  const yaw = (yawDegrees * Math.PI) / 180;
  const pitch = (pitchDegrees * Math.PI) / 180;
  return (point: Point3): ProjectionPoint => {
    const across = point.x * Math.cos(yaw) - point.y * Math.sin(yaw);
    const rearward = point.x * Math.sin(yaw) + point.y * Math.cos(yaw);
    return {
      x: across,
      y: -(rearward * Math.sin(pitch) + point.z * Math.cos(pitch)),
      depth: -rearward * Math.cos(pitch) + point.z * Math.sin(pitch),
    };
  };
}

/** Display only the finite canonical facets present in this step. */
export function projectConstructionFacets(
  facets: readonly CanonicalFacet[],
  project: (point: Point3) => ProjectionPoint,
) {
  return facets
    .filter(
      (facet) =>
        facet.vertices.length >= 3 &&
        facet.vertices.every(finitePoint) &&
        finitePoint(facet.centroid),
    )
    .map((facet) => ({
      ...facet,
      points: facet.vertices.map(project),
      center: project(facet.centroid),
    }))
    .filter((facet) =>
      [...facet.points, facet.center].every((p) =>
        [p.x, p.y, p.depth].every(Number.isFinite),
      ),
    );
}

/** Fit the displayed geometry, never the world origin or absent pieces. */
export function fitConstructionProjection(points: readonly ProjectionPoint[]) {
  const finite = points.filter(
    (p) => Number.isFinite(p.x) && Number.isFinite(p.y),
  );
  const minX = finite.length ? Math.min(...finite.map((p) => p.x)) : 0;
  const maxX = finite.length ? Math.max(...finite.map((p) => p.x)) : 0;
  const minY = finite.length ? Math.min(...finite.map((p) => p.y)) : 0;
  const maxY = finite.length ? Math.max(...finite.map((p) => p.y)) : 0;
  const width = maxX - minX,
    height = maxY - minY;
  const scale = 310 / Math.max(width, height, 1e-9);
  return {
    width,
    height,
    x: (value: number) => 200 + (value - (minX + maxX) / 2) * scale,
    y: (value: number) => 190 + (value - (minY + maxY) / 2) * scale,
  };
}

export function orthographicConstruction(
  facets: readonly CanonicalFacet[],
  view: ConstructionView,
) {
  const projected = projectConstructionFacets(facets, (p) =>
    view === "top"
      ? { x: p.x, y: -p.y, depth: p.z }
      : view === "front"
        ? { x: p.x, y: -p.z, depth: -p.y }
        : { x: p.y, y: -p.z, depth: p.x },
  );
  return {
    facets: projected,
    fit: fitConstructionProjection(projected.flatMap((f) => f.points)),
  };
}
