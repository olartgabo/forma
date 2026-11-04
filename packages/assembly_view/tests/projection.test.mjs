import assert from "node:assert/strict";
import test from "node:test";
import { initialCamera, projectFacets } from "../projection.ts";

const facets = [
  {
    facet_id: "base-face",
    part_id: "base",
    centroid: { x: 0.1, y: 0.1, z: 0 },
    vertices: [
      { x: 0, y: 0, z: 0 },
      { x: 0.2, y: 0, z: 0 },
      { x: 0.2, y: 0.2, z: 0 },
      { x: 0, y: 0.2, z: 0 },
    ],
  },
  {
    facet_id: "back-face",
    part_id: "back",
    centroid: { x: 0.1, y: 0.2, z: 0.1 },
    vertices: [
      { x: 0, y: 0.2, z: 0 },
      { x: 0.2, y: 0.2, z: 0 },
      { x: 0.2, y: 0.2, z: 0.2 },
      { x: 0, y: 0.2, z: 0.2 },
    ],
  },
];
test("camera and separation project exact source facets without mutating geometry", () => {
  const before = structuredClone(facets);
  const first = projectFacets(facets, initialCamera);
  const moved = projectFacets(facets, {
    ...initialCamera,
    yaw: 40,
    pitch: -20,
    zoom: 1.4,
    explode: 1,
  });
  assert.deepEqual(facets, before);
  assert.notDeepEqual(
    first.map((f) => f.points),
    moved.map((f) => f.points),
  );
  assert.deepEqual(
    new Set(moved.map((f) => f.part_id)),
    new Set(["base", "back"]),
  );
  for (const facet of moved)
    for (const point of facet.points)
      assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
});
test("separation preserves each facet shape and does not double count a folded part", () => {
  const folded = [
    ...facets,
    { ...facets[1], facet_id: "back-fold", part_id: "back" },
  ];
  const normal = projectFacets(folded, initialCamera),
    separated = projectFacets(folded, { ...initialCamera, explode: 1 });
  const byId = new Map(normal.map((f) => [f.facet_id, f]));
  for (const face of separated) {
    const source = byId.get(face.facet_id);
    const offset = face.points[0].x - source.points[0].x;
    for (let index = 0; index < 4; index++) {
      assert.ok(
        Math.abs(face.points[index].x - source.points[index].x - offset) <
          1e-10,
      );
      assert.equal(face.points[index].y, source.points[index].y);
    }
  }
  const backs = separated.filter((f) => f.part_id === "back");
  assert.deepEqual(backs[0].points, backs[1].points);
});
