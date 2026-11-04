// Display-only orthographic projection. Input coordinates remain in SI metres.
export type Point = { x: number; y: number; z: number };
export type Facet = {
  facet_id: string;
  part_id: string;
  feature_id?: string | null;
  vertices: readonly Point[];
  centroid: Point;
};
export type Camera = {
  yaw: number;
  pitch: number;
  zoom: number;
  explode: number;
};
export const initialCamera: Camera = {
  yaw: -35,
  pitch: 25,
  zoom: 1,
  explode: 0,
};
export function projectFacets(facets: readonly Facet[], camera: Camera) {
  const vertices = facets.flatMap((facet) => facet.vertices);
  const axes = ["x", "y", "z"] as const;
  const bounds = axes.map((axis) => {
    const values = vertices.map((p) => p[axis]);
    return [Math.min(...values), Math.max(...values)];
  });
  const center = bounds.map(([lo, hi]) => lo / 2 + hi / 2);
  const span = Math.max(...bounds.map(([lo, hi]) => hi - lo), 0.001);
  const yaw = (camera.yaw * Math.PI) / 180,
    pitch = (camera.pitch * Math.PI) / 180;
  const partIds = [...new Set(facets.map((f) => f.part_id))].sort();
  const rotate = (point: Point, part: string) => {
    const rank = partIds.indexOf(part);
    // Separate source parts along the display's horizontal axis, never a joint axis.
    const separation = (rank - (partIds.length - 1) / 2) * camera.explode * 0.5;
    const x = (point.x - center[0]) / span;
    const y = (point.y - center[1]) / span;
    const z = (point.z - center[2]) / span;
    const horizontal = x * Math.cos(yaw) - y * Math.sin(yaw);
    const depth = x * Math.sin(yaw) + y * Math.cos(yaw);
    return {
      x: 240 + (horizontal + separation) * 145 * camera.zoom,
      y:
        190 -
        (z * Math.cos(pitch) - depth * Math.sin(pitch)) * 145 * camera.zoom,
      depth: depth * Math.cos(pitch) + z * Math.sin(pitch),
    };
  };
  return facets
    .map((facet) => ({
      ...facet,
      points: facet.vertices.map((p) => rotate(p, facet.part_id)),
      label: rotate(facet.centroid, facet.part_id),
    }))
    .sort((a, b) => a.label.depth - b.label.depth);
}
