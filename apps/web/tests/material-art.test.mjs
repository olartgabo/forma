import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { test } from "node:test";
import sharp from "sharp";
import { MATERIAL_CATALOG } from "../src/lib/generated/material-catalog.ts";
import { materialArt, toolArt } from "../src/lib/material-art.ts";

const publicRoot = new URL("../public/", import.meta.url);

test("every catalog category maps to its own existing, transparent, bounded WebP", async () => {
  assert.equal(MATERIAL_CATALOG.categories.length, 48);
  const sources = new Set();
  for (const [index, category] of MATERIAL_CATALOG.categories.entries()) {
    const art = materialArt(category.id);
    assert.ok(art, category.id);
    assert.equal(art.label, category.label);
    assert.match(
      art.src,
      new RegExp(
        `^/materials/${String(index + 1).padStart(2, "0")}-[a-z-]+\\.webp$`,
      ),
    );
    const file = new URL(art.src.slice(1), publicRoot);
    const metadata = await sharp(await readFile(file)).metadata();
    assert.equal(metadata.format, "webp");
    assert.ok(metadata.width > 0 && metadata.width <= 720);
    assert.ok(metadata.height > 0 && metadata.height <= 720);
    assert.equal(metadata.hasAlpha, true);
    assert.equal((await sharp(await readFile(file)).stats()).isOpaque, false);
    assert.ok((await stat(file)).size <= 240 * 1024);
    sources.add(art.src);
  }
  assert.equal(sources.size, 48);
});

test("unknown material IDs never guess art or use object prototype values", () => {
  for (const id of [
    "",
    "cardboard",
    "Corrugated_cardboard",
    "wood",
    "__proto__",
    "constructor",
  ]) {
    assert.equal(materialArt(id), null);
  }
});

test("tools use explicit aliases and case-only normalization", async () => {
  const pairs = [
    ["SCISSORS", "49-scissors"],
    ["utility knife", "50-utility-knife"],
    ["Craft knife", "50-utility-knife"],
    ["box cutter", "50-utility-knife"],
    ["RULER", "51-ruler"],
    ["metal ruler", "51-ruler"],
    ["straightedge", "51-ruler"],
    ["tape measure", "52-measuring-tape"],
    ["Pencil", "53-pencil"],
    ["cutting mat", "54-cutting-mat"],
    ["Hot glue gun", "55-hot-glue-gun"],
    ["screwdriver", "56-screwdriver"],
    ["pliers", "57-pliers"],
    ["handsaw", "58-hand-saw"],
    ["drill", "59-drill"],
    ["clamps", "60-clamp"],
  ];
  for (const [alias, basename] of pairs) {
    const art = toolArt(alias);
    assert.ok(art, alias);
    assert.equal(art.src, `/materials/${basename}.webp`);
    assert.ok((await stat(new URL(art.src.slice(1), publicRoot))).size > 0);
  }
  for (const label of [
    "",
    "knife",
    "scissors and ruler",
    " scissors",
    "ruler ",
    "utility-knife",
    "laser cutter",
    "__proto__",
    "constructor",
  ]) {
    assert.equal(toolArt(label), null, label);
  }
});

test("manifest includes all 60 transparent optimized assets", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("materials/manifest.json", publicRoot), "utf8"),
  );
  assert.equal(manifest.records.length, 60);
  for (const record of manifest.records) {
    assert.equal(record.transparent, true);
    assert.ok(record.width <= 720 && record.height <= 720);
    assert.equal(
      (await stat(new URL(`materials/${record.file}`, publicRoot))).size,
      record.bytes,
    );
    const asset = await readFile(
      new URL(`materials/${record.file}`, publicRoot),
    );
    const metadata = await sharp(asset).metadata();
    assert.equal(metadata.width, record.width);
    assert.equal(metadata.height, record.height);
    assert.equal((await sharp(asset).stats()).isOpaque, false);
  }
});
