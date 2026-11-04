import assert from "node:assert/strict";
import { test } from "node:test";
import { projectEngineModel } from "../src/lib/engine-model-projection.ts";

const point = (x, y, z) => ({ x, y, z });
const facet = (id, vertices) => ({
  facet_id: id,
  part_id: `part-${id}`,
  vertices,
  centroid: point(0, 0, 0),
  area_fraction: 1,
});
// Deliberately unnamed surface arrangements: neither needs a project family.
const a = {
  facets: [
    facet("a", [
      point(-4, -3, -2),
      point(2, -3, -2),
      point(2, 1, -2),
      point(-4, 1, -2),
    ]),
    facet("b", [
      point(-4, 1, -2),
      point(2, 1, -2),
      point(2, 1, 4),
      point(-4, 1, 4),
    ]),
  ],
};
const b = {
  facets: [
    facet("q", [point(-8, -2, -1), point(-5, -2, -1), point(-6, 1, 3)]),
    facet("r", [point(2, 5, 0), point(5, 5, 0), point(4, 9, 2)]),
  ],
};
const coordinates = (result) =>
  result.flatMap((f) =>
    f.points.split(" ").map((p) => p.split(",").map(Number)),
  );

test("different unnamed native surfaces produce distinct fitted captures with all disconnected components", () => {
  const first = projectEngineModel(a),
    second = projectEngineModel(b);
  assert.equal(first.length, 2);
  assert.equal(second.length, 2);
  assert.notDeepEqual(
    first.map((f) => f.points),
    second.map((f) => f.points),
  );
  for (const result of [first, second]) {
    const points = coordinates(result);
    assert.ok(
      points.every(([x, y]) => x >= 24 && x <= 336 && y >= 24 && y <= 216),
    );
    const minX = Math.min(...points.map(([x]) => x)),
      maxX = Math.max(...points.map(([x]) => x));
    const minY = Math.min(...points.map(([, y]) => y)),
      maxY = Math.max(...points.map(([, y]) => y));
    assert.ok(Math.abs(minX + maxX - 360) < 0.002);
    assert.ok(Math.abs(minY + maxY - 240) < 0.002);
    assert.ok(
      Math.abs(maxX - minX - 312) < 0.002 ||
        Math.abs(maxY - minY - 192) < 0.002,
    );
    assert.ok(
      result.every(
        (f) => Number.isFinite(f.depth) && f.light >= 0 && f.light <= 1,
      ),
    );
  }
  assert.notEqual(first[0].light, first[1].light);
});

test("translation and uniform scale preserve the capture including negative and far-off origins", () => {
  const transform = (geometry, scale, translation) => ({
    facets: geometry.facets.map((f) => ({
      ...f,
      vertices: f.vertices.map((p) =>
        point(
          p.x * scale + translation.x,
          p.y * scale + translation.y,
          p.z * scale + translation.z,
        ),
      ),
    })),
  });
  for (const geometry of [a, b]) {
    const original = projectEngineModel(geometry);
    for (const candidate of [
      transform(geometry, 1, point(-312, 888, -58)),
      transform(geometry, 0.001, point(500000, -500000, 10)),
      transform(geometry, 20, point(0, 0, 0)),
    ]) {
      const result = projectEngineModel(candidate);
      assert.deepEqual(
        result.map((f) => f.points),
        original.map((f) => f.points),
      );
      result.forEach((f, i) =>
        assert.ok(Math.abs(f.light - original[i].light) < 1e-6),
      );
    }
  }
});

test("invalid, nonfinite, degenerate and oversized inputs fail closed", () => {
  const change = (value) => ({
    facets: [
      facet("bad", [point(value, 0, 0), point(1, 0, 0), point(0, 1, 0)]),
    ],
  });
  for (const geometry of [
    null,
    {},
    { facets: [] },
    change(NaN),
    change(Infinity),
    change(-Infinity),
    change(1e8),
    change("3"),
    {
      facets: [facet("flat", [point(1, 1, 1), point(2, 2, 2), point(3, 3, 3)])],
    },
    { facets: [a.facets[0], a.facets[0]] },
    { facets: [{ ...a.facets[0], vertices: Array(257).fill(point(0, 0, 0)) }] },
    { facets: Array(129).fill(a.facets[0]) },
  ]) {
    assert.equal(projectEngineModel(geometry), null);
  }
});

test("faces are drawn far to near regardless of their source order", () => {
  const near = facet("near", [
    point(1, -1, 2),
    point(2, -1, 2),
    point(1, 0, 2),
  ]);
  const far = facet("far", [
    point(1, -1, -2),
    point(2, -1, -2),
    point(1, 0, -2),
  ]);
  const first = projectEngineModel({ facets: [near, far] });
  assert.deepEqual(
    first.map((f) => f.facetId),
    ["far", "near"],
  );
  assert.deepEqual(first, projectEngineModel({ facets: [far, near] }));
});
