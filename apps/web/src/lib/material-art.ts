// Prepared from the existing reference PNGs by tools/prepare-material-art.mjs.
// Illustrative recognition art; never geometry or physical evidence.

export type MaterialArt = { src: string; label: string };

const materials: Record<string, MaterialArt> = {
  corrugated_cardboard: {
    src: "/materials/01-corrugated-cardboard.webp",
    label: "Corrugated cardboard",
  },
  thin_packaging_card: {
    src: "/materials/02-thin-packaging-card.webp",
    label: "Thin packaging card",
  },
  cardstock: {
    src: "/materials/03-cardstock.webp",
    label: "Cardstock",
  },
  printer_paper: {
    src: "/materials/04-printer-paper.webp",
    label: "Printer paper",
  },
  kraft_paper: {
    src: "/materials/05-kraft-paper.webp",
    label: "Kraft paper",
  },
  paper_tube: {
    src: "/materials/06-paper-tube.webp",
    label: "Paper tube",
  },
  egg_carton: {
    src: "/materials/07-egg-carton.webp",
    label: "Egg carton",
  },
  paper_cup: {
    src: "/materials/08-paper-cup.webp",
    label: "Paper cup",
  },
  craft_sticks: {
    src: "/materials/09-craft-stick.webp",
    label: "Craft sticks",
  },
  bamboo_skewers: {
    src: "/materials/10-bamboo-skewer.webp",
    label: "Bamboo skewers",
  },
  toothpicks: {
    src: "/materials/11-toothpick.webp",
    label: "Toothpicks",
  },
  wooden_dowels: {
    src: "/materials/12-wooden-dowel.webp",
    label: "Wooden dowels",
  },
  wood_strips: {
    src: "/materials/13-wood-strip.webp",
    label: "Wood strips",
  },
  small_wood_offcuts: {
    src: "/materials/14-wood-offcut.webp",
    label: "Small wood offcuts",
  },
  plywood_sheet: {
    src: "/materials/15-plywood-sheet.webp",
    label: "Plywood sheet",
  },
  cork_sheet: {
    src: "/materials/16-cork-sheet.webp",
    label: "Cork sheet",
  },
  plastic_bottle: {
    src: "/materials/17-plastic-bottle.webp",
    label: "Plastic bottle",
  },
  bottle_caps: {
    src: "/materials/18-bottle-cap.webp",
    label: "Bottle caps",
  },
  food_container: {
    src: "/materials/19-food-container.webp",
    label: "Food container",
  },
  plastic_lid: {
    src: "/materials/20-plastic-lid.webp",
    label: "Plastic lid",
  },
  plastic_sheet: {
    src: "/materials/21-plastic-sheet.webp",
    label: "Plastic sheet",
  },
  plastic_packaging_tray: {
    src: "/materials/22-plastic-packaging-tray.webp",
    label: "Plastic packaging tray",
  },
  drinking_straws: {
    src: "/materials/23-drinking-straw.webp",
    label: "Drinking straws",
  },
  pvc_pipe: {
    src: "/materials/24-pvc-pipe.webp",
    label: "PVC pipe",
  },
  foam_board: {
    src: "/materials/25-foam-board.webp",
    label: "Foam board",
  },
  eva_craft_foam: {
    src: "/materials/26-eva-foam.webp",
    label: "EVA craft foam",
  },
  expanded_polystyrene: {
    src: "/materials/27-expanded-polystyrene.webp",
    label: "Expanded polystyrene",
  },
  packing_foam: {
    src: "/materials/28-packing-foam.webp",
    label: "Packing foam",
  },
  sponge: {
    src: "/materials/29-sponge.webp",
    label: "Sponge",
  },
  felt: {
    src: "/materials/30-felt.webp",
    label: "Felt",
  },
  fabric_scrap: {
    src: "/materials/31-fabric-scrap.webp",
    label: "Fabric scrap",
  },
  denim_scrap: {
    src: "/materials/32-denim-scrap.webp",
    label: "Denim scrap",
  },
  duct_tape: {
    src: "/materials/33-duct-tape.webp",
    label: "Duct tape",
  },
  masking_tape: {
    src: "/materials/34-masking-tape.webp",
    label: "Masking tape",
  },
  clear_tape: {
    src: "/materials/35-clear-tape.webp",
    label: "Clear tape",
  },
  double_sided_tape: {
    src: "/materials/36-double-sided-tape.webp",
    label: "Double-sided tape",
  },
  electrical_tape: {
    src: "/materials/37-electrical-tape.webp",
    label: "Electrical tape",
  },
  white_glue: {
    src: "/materials/38-white-glue.webp",
    label: "White glue",
  },
  glue_stick: {
    src: "/materials/39-glue-stick.webp",
    label: "Glue stick",
  },
  hot_glue_sticks: {
    src: "/materials/40-hot-glue-stick.webp",
    label: "Hot-glue sticks",
  },
  string_twine: {
    src: "/materials/41-string-twine.webp",
    label: "String or twine",
  },
  zip_ties: {
    src: "/materials/42-zip-tie.webp",
    label: "Zip ties",
  },
  rubber_bands: {
    src: "/materials/43-rubber-band.webp",
    label: "Rubber bands",
  },
  paper_clips: {
    src: "/materials/44-paper-clip.webp",
    label: "Paper clips",
  },
  binder_clips: {
    src: "/materials/45-binder-clip.webp",
    label: "Binder clips",
  },
  aluminum_foil: {
    src: "/materials/46-aluminum-foil.webp",
    label: "Aluminium foil",
  },
  wire: {
    src: "/materials/47-wire.webp",
    label: "Wire",
  },
  nuts_and_bolts: {
    src: "/materials/48-nut-and-bolt.webp",
    label: "Nuts and bolts",
  },
};

const tools: Record<string, MaterialArt> = {
  scissors: {
    src: "/materials/49-scissors.webp",
    label: "Scissors",
  },
  "utility knife": {
    src: "/materials/50-utility-knife.webp",
    label: "Utility knife",
  },
  "craft knife": {
    src: "/materials/50-utility-knife.webp",
    label: "Utility knife",
  },
  "box cutter": {
    src: "/materials/50-utility-knife.webp",
    label: "Utility knife",
  },
  cutter: {
    src: "/materials/50-utility-knife.webp",
    label: "Utility knife",
  },
  ruler: {
    src: "/materials/51-ruler.webp",
    label: "Ruler",
  },
  "metal ruler": {
    src: "/materials/51-ruler.webp",
    label: "Ruler",
  },
  straightedge: {
    src: "/materials/51-ruler.webp",
    label: "Ruler",
  },
  "measuring tape": {
    src: "/materials/52-measuring-tape.webp",
    label: "Measuring tape",
  },
  "tape measure": {
    src: "/materials/52-measuring-tape.webp",
    label: "Measuring tape",
  },
  pencil: {
    src: "/materials/53-pencil.webp",
    label: "Pencil",
  },
  "cutting mat": {
    src: "/materials/54-cutting-mat.webp",
    label: "Cutting mat",
  },
  "hot-glue gun": {
    src: "/materials/55-hot-glue-gun.webp",
    label: "Hot-glue gun",
  },
  "hot glue gun": {
    src: "/materials/55-hot-glue-gun.webp",
    label: "Hot-glue gun",
  },
  "glue gun": {
    src: "/materials/55-hot-glue-gun.webp",
    label: "Hot-glue gun",
  },
  screwdriver: {
    src: "/materials/56-screwdriver.webp",
    label: "Screwdriver",
  },
  pliers: {
    src: "/materials/57-pliers.webp",
    label: "Pliers",
  },
  "hand saw": {
    src: "/materials/58-hand-saw.webp",
    label: "Hand saw",
  },
  handsaw: {
    src: "/materials/58-hand-saw.webp",
    label: "Hand saw",
  },
  drill: {
    src: "/materials/59-drill.webp",
    label: "Drill",
  },
  clamp: {
    src: "/materials/60-clamp.webp",
    label: "Clamp",
  },
  clamps: {
    src: "/materials/60-clamp.webp",
    label: "Clamp",
  },
};

export function materialArt(categoryId: string): MaterialArt | null {
  return Object.hasOwn(materials, categoryId) ? materials[categoryId] : null;
}

export function toolArt(label: string): MaterialArt | null {
  const key = label.toLowerCase();
  return Object.hasOwn(tools, key) ? tools[key] : null;
}
