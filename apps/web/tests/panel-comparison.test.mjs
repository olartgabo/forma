import assert from "node:assert/strict";
import { test } from "node:test";
import { panelComparisons } from "../src/lib/panel-comparison.ts";

test("pairs changed panels with their originals in new-manual order", () => {
  // Shape of a brace replacement: a new cut is inserted first, the original
  // cut keeps its panel, and later steps shift and change.
  const diff = {
    unchanged: [1],
    changed: [2, 3, 8],
    changed_from: [1, 2, 7],
    added: [0],
    removed: [],
  };
  assert.deepEqual(panelComparisons(diff, 8, 9), [
    { kind: "added", index: 0 },
    { kind: "changed", index: 2, previous: 1 },
    { kind: "changed", index: 3, previous: 2 },
    { kind: "changed", index: 8, previous: 7 },
  ]);
});

test("lists removed original panels after the updated ones", () => {
  const diff = {
    unchanged: [0],
    changed: [1],
    changed_from: [2],
    added: [],
    removed: [1, 3],
  };
  assert.deepEqual(panelComparisons(diff, 4, 2), [
    { kind: "changed", index: 1, previous: 2 },
    { kind: "removed", previous: 1 },
    { kind: "removed", previous: 3 },
  ]);
});

test("refuses a changed panel without its original", () => {
  assert.throws(
    () =>
      panelComparisons(
        {
          unchanged: [],
          changed: [0, 1],
          changed_from: [0],
          added: [],
          removed: [],
        },
        2,
        2,
      ),
    /original panel/,
  );
});

test("an unchanged revision has nothing to compare", () => {
  assert.deepEqual(
    panelComparisons(
      {
        unchanged: [0, 1],
        changed: [],
        changed_from: [],
        added: [],
        removed: [],
      },
      2,
      2,
    ),
    [],
  );
});

test("refuses indices outside either manual", () => {
  const diff = {
    unchanged: [],
    changed: [1],
    changed_from: [3],
    added: [],
    removed: [],
  };
  assert.throws(() => panelComparisons(diff, 3, 2), /missing panel/);
  assert.throws(
    () => panelComparisons({ ...diff, changed_from: [0] }, 3, 1),
    /missing panel/,
  );
  assert.throws(
    () => panelComparisons({ ...diff, changed_from: [0], removed: [5] }, 3, 2),
    /missing panel/,
  );
  assert.equal(
    panelComparisons({ ...diff, changed_from: [2] }, 3, 2).length,
    1,
  );
});
