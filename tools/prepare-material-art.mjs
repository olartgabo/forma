import { readFile, readdir, mkdir, writeFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import sharp from "sharp";
import prettier from "prettier";

const root = fileURLToPath(new URL("../", import.meta.url));
const source = path.resolve(
  root,
  "../output/material-library-reference-pose-20261104",
);
const destination = path.join(root, "apps/web/public/materials");
const catalogText = await readFile(
  path.join(root, "apps/web/src/lib/generated/material-catalog.ts"),
  "utf8",
);
const categories = [
  ...catalogText.matchAll(/"id": "([^"]+)",\s+"label": "([^"]+)"/g),
].map((match) => ({ id: match[1], label: match[2] }));
const files = (await readdir(source))
  .filter((file) => /^\d{2}-.+\.png$/.test(file))
  .sort();
if (categories.length !== 48 || files.length !== 60)
  throw new Error("Expected 48 categories and 60 reference PNGs");
const toolLabels = [
  "Scissors",
  "Utility knife",
  "Ruler",
  "Measuring tape",
  "Pencil",
  "Cutting mat",
  "Hot-glue gun",
  "Screwdriver",
  "Pliers",
  "Hand saw",
  "Drill",
  "Clamp",
];
const aliases = [
  ["scissors"],
  ["utility knife", "craft knife", "box cutter", "cutter"],
  ["ruler", "metal ruler", "straightedge"],
  ["measuring tape", "tape measure"],
  ["pencil"],
  ["cutting mat"],
  ["hot-glue gun", "hot glue gun", "glue gun"],
  ["screwdriver"],
  ["pliers"],
  ["hand saw", "handsaw"],
  ["drill"],
  ["clamp", "clamps"],
];
await mkdir(destination, { recursive: true });
const materials = {};
const tools = {};
const records = [];
for (const [index, file] of files.entries()) {
  const input = path.join(source, file);
  const name = file.replace(/\.png$/, ".webp");
  const output = path.join(destination, name);
  const metadata = await sharp(input).metadata();
  if (!metadata.hasAlpha)
    throw new Error(`${file} has no transparency channel`);
  const cropped = await sharp(input)
    .trim({ threshold: 10 })
    .resize({
      width: 720,
      height: 720,
      fit: "inside",
      withoutEnlargement: true,
    })
    .png()
    .toBuffer();
  const info = await sharp(cropped)
    .webp({ quality: 76, alphaQuality: 100, effort: 3 })
    .toFile(output);
  // Texture-heavy references may exceed the soft 120KB target.
  if (info.size > 240 * 1024)
    throw new Error(`${name} exceeds the byte budget`);
  const stats = await sharp(output).stats();
  if (stats.isOpaque) throw new Error(`${name} lost transparency`);
  const art = {
    src: `/materials/${name}`,
    label: categories[index]?.label ?? toolLabels[index - 48],
  };
  if (index < 48) materials[categories[index].id] = art;
  else for (const alias of aliases[index - 48]) tools[alias] = art;
  records.push({
    file: name,
    sourceBytes: (await stat(input)).size,
    bytes: info.size,
    width: info.width,
    height: info.height,
    transparent: true,
  });
}
const code = `// Prepared from the existing reference PNGs by tools/prepare-material-art.mjs.\n// Illustrative recognition art; never geometry or physical evidence.\n\nexport type MaterialArt = { src: string; label: string };\n\nconst materials: Record<string, MaterialArt> = ${JSON.stringify(materials, null, 2)};\n\nconst tools: Record<string, MaterialArt> = ${JSON.stringify(tools, null, 2)};\n\nexport function materialArt(categoryId: string): MaterialArt | null {\n  return Object.hasOwn(materials, categoryId) ? materials[categoryId] : null;\n}\n\nexport function toolArt(label: string): MaterialArt | null {\n  const key = label.toLowerCase();\n  return Object.hasOwn(tools, key) ? tools[key] : null;\n}\n`;
await writeFile(
  path.join(root, "apps/web/src/lib/material-art.ts"),
  await prettier.format(code, { parser: "typescript" }),
);
await writeFile(
  path.join(destination, "manifest.json"),
  JSON.stringify(
    { source: "material-library-reference-pose-20261104", records },
    null,
    2,
  ) + "\n",
);
console.log(
  JSON.stringify({
    count: records.length,
    sourceBytes: records.reduce((sum, record) => sum + record.sourceBytes, 0),
    bytes: records.reduce((sum, record) => sum + record.bytes, 0),
    minBytes: Math.min(...records.map((record) => record.bytes)),
    maxBytes: Math.max(...records.map((record) => record.bytes)),
    maxDimension: Math.max(
      ...records.flatMap((record) => [record.width, record.height]),
    ),
    transparent: records.filter((record) => record.transparent).length,
  }),
);
