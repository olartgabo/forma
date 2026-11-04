"""The initial recognition catalog (#177 follow-up).

These are recognition categories: what a visible object probably is. They are
not fabrication materials. Object identity, the suggested material family, the
visible form and fabrication support are separate fields, and only the few
categories that map onto existing build rules link to a ``Stock`` kind and
material. Everything else is "Identified; build rules not available yet".

Nothing here is a measured or physical fact: composition, thickness,
strength, mass and remaining quantity stay unknown.
"""

from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator

from .models import ID, Record, Text

CATALOG_VERSION = "material-catalog-v1"

CategoryId = Literal[
    # Paper / cardboard
    "corrugated_cardboard",
    "thin_packaging_card",
    "cardstock",
    "printer_paper",
    "kraft_paper",
    "paper_tube",
    "egg_carton",
    "paper_cup",
    # Wood / plant
    "craft_sticks",
    "bamboo_skewers",
    "toothpicks",
    "wooden_dowels",
    "wood_strips",
    "small_wood_offcuts",
    "plywood_sheet",
    "cork_sheet",
    # Plastic
    "plastic_bottle",
    "bottle_caps",
    "food_container",
    "plastic_lid",
    "plastic_sheet",
    "plastic_packaging_tray",
    "drinking_straws",
    "pvc_pipe",
    # Foam / soft
    "foam_board",
    "eva_craft_foam",
    "expanded_polystyrene",
    "packing_foam",
    "sponge",
    "felt",
    "fabric_scrap",
    "denim_scrap",
    # Tape / adhesives / ties
    "duct_tape",
    "masking_tape",
    "clear_tape",
    "double_sided_tape",
    "electrical_tape",
    "white_glue",
    "glue_stick",
    "hot_glue_sticks",
    "string_twine",
    "zip_ties",
    # Connectors / metal
    "rubber_bands",
    "paper_clips",
    "binder_clips",
    "aluminum_foil",
    "wire",
    "nuts_and_bolts",
]
CATEGORY_IDS: tuple[str, ...] = get_args(CategoryId)

Group = Literal[
    "paper_cardboard",
    "wood_plant",
    "plastic",
    "foam_soft",
    "tape_adhesive_tie",
    "connector_metal",
]

# Visible form decides which measurements a photo can support.
Form = Literal[
    "flat_sheet",  # thin and flat on the reference plane
    "thick_sheet",  # flat but with a raised top face
    "soft_sheet",  # flat as laid; shape changes when moved
    "stick_strip",  # straight, lying flat
    "tube",
    "container_3d",
    "block_3d",
    "small_part",
    "roll",
    "adhesive_container",
    "loose_cord",
]

Capability = Literal[
    "planar_outline",
    "planar_outline_top_face",
    "planar_outline_as_laid",
    "length_and_width",
    "ruler_or_more_views",
    "no_quantity_from_photo",
]

CAPABILITY_FOR_FORM: dict[str, str] = {
    "flat_sheet": "planar_outline",
    "thick_sheet": "planar_outline_top_face",
    "soft_sheet": "planar_outline_as_laid",
    "stick_strip": "length_and_width",
    "tube": "ruler_or_more_views",
    "container_3d": "ruler_or_more_views",
    "block_3d": "ruler_or_more_views",
    "small_part": "ruler_or_more_views",
    "roll": "no_quantity_from_photo",
    "adhesive_container": "no_quantity_from_photo",
    "loose_cord": "no_quantity_from_photo",
}

CAPABILITY_TEXT: dict[str, str] = {
    "planar_outline": "Photo outline and flat size, beside the printed card.",
    "planar_outline_top_face": (
        "Photo outline only with the card on the same top face; otherwise "
        "measure with a ruler. Thickness is never estimated."
    ),
    "planar_outline_as_laid": (
        "Photo outline of the piece as it lies; soft material can stretch, so "
        "check sizes that matter with a ruler."
    ),
    "length_and_width": (
        "Visible length and width when it lies straight and flat beside the "
        "card; round pieces are assumed thin compared with the camera distance."
    ),
    "ruler_or_more_views": (
        "No size from one photo. Measure with a ruler, or add more views once "
        "multi-view measurement exists."
    ),
    "no_quantity_from_photo": (
        "How much is left cannot be seen from a photo. Enter it if you know it."
    ),
}

SupportStatus = Literal["build_rules_available", "build_rules_not_available"]


class CategoryInfo(Record):
    id: CategoryId
    label: Text
    group: Group
    form: Form
    # A material family to suggest, never a confirmed composition.
    material_family: Text
    composition_unknown: bool
    support: SupportStatus
    stock_kind: Literal["sheet", "strip", "tape", "cord"] | None = None
    stock_material: Literal["cardboard", "paperboard", "other_supported"] | None = None
    support_note: Text | None = None

    @model_validator(mode="after")
    def consistent(self):
        linked = self.stock_kind is not None and self.stock_material is not None
        if (self.support == "build_rules_available") != linked:
            raise ValueError("only categories with build rules link to a stock")
        return self


def _c(
    id,
    label,
    group,
    form,
    family,
    *,
    unknown=False,
    kind=None,
    material=None,
    note=None,
):
    return CategoryInfo(
        id=id,
        label=label,
        group=group,
        form=form,
        material_family=family,
        composition_unknown=unknown,
        support="build_rules_available" if kind else "build_rules_not_available",
        stock_kind=kind,
        stock_material=material,
        support_note=note,
    )


_TAPE = "Generic tape-joint rules; adhesion of this tape is not tested."
CATALOG: tuple[CategoryInfo, ...] = (
    _c(
        "corrugated_cardboard",
        "Corrugated cardboard",
        "paper_cardboard",
        "flat_sheet",
        "corrugated board",
        kind="sheet",
        material="cardboard",
    ),
    _c(
        "thin_packaging_card",
        "Thin packaging card",
        "paper_cardboard",
        "flat_sheet",
        "paperboard",
        kind="sheet",
        material="paperboard",
        note="Paperboard rules; thickness still needs a ruler.",
    ),
    _c(
        "cardstock",
        "Cardstock",
        "paper_cardboard",
        "flat_sheet",
        "paperboard",
        kind="sheet",
        material="paperboard",
        note="Paperboard rules; thickness still needs a ruler.",
    ),
    _c("printer_paper", "Printer paper", "paper_cardboard", "flat_sheet", "paper"),
    _c("kraft_paper", "Kraft paper", "paper_cardboard", "flat_sheet", "paper"),
    _c("paper_tube", "Paper tube", "paper_cardboard", "tube", "paperboard"),
    _c(
        "egg_carton",
        "Egg carton",
        "paper_cardboard",
        "container_3d",
        "moulded pulp",
        unknown=True,
    ),
    _c(
        "paper_cup",
        "Paper cup",
        "paper_cardboard",
        "container_3d",
        "coated paper",
        unknown=True,
    ),
    _c("craft_sticks", "Craft sticks", "wood_plant", "stick_strip", "wood"),
    _c("bamboo_skewers", "Bamboo skewers", "wood_plant", "stick_strip", "bamboo"),
    _c(
        "toothpicks",
        "Toothpicks",
        "wood_plant",
        "stick_strip",
        "wood or bamboo",
        unknown=True,
    ),
    _c("wooden_dowels", "Wooden dowels", "wood_plant", "stick_strip", "wood"),
    _c("wood_strips", "Wood strips", "wood_plant", "stick_strip", "wood"),
    _c("small_wood_offcuts", "Small wood offcuts", "wood_plant", "block_3d", "wood"),
    _c("plywood_sheet", "Plywood sheet", "wood_plant", "thick_sheet", "plywood"),
    _c("cork_sheet", "Cork sheet", "wood_plant", "thick_sheet", "cork"),
    _c(
        "plastic_bottle",
        "Plastic bottle",
        "plastic",
        "container_3d",
        "plastic",
        unknown=True,
    ),
    _c("bottle_caps", "Bottle caps", "plastic", "small_part", "plastic", unknown=True),
    _c(
        "food_container",
        "Food container",
        "plastic",
        "container_3d",
        "plastic",
        unknown=True,
    ),
    _c(
        "plastic_lid", "Plastic lid", "plastic", "container_3d", "plastic", unknown=True
    ),
    _c(
        "plastic_sheet",
        "Plastic sheet",
        "plastic",
        "flat_sheet",
        "plastic",
        unknown=True,
    ),
    _c(
        "plastic_packaging_tray",
        "Plastic packaging tray",
        "plastic",
        "container_3d",
        "plastic",
        unknown=True,
    ),
    _c(
        "drinking_straws",
        "Drinking straws",
        "plastic",
        "stick_strip",
        "plastic or paper",
        unknown=True,
    ),
    _c("pvc_pipe", "PVC pipe", "plastic", "tube", "PVC"),
    _c(
        "foam_board",
        "Foam board",
        "foam_soft",
        "thick_sheet",
        "foam core with paper faces",
    ),
    _c("eva_craft_foam", "EVA craft foam", "foam_soft", "thick_sheet", "EVA foam"),
    _c(
        "expanded_polystyrene",
        "Expanded polystyrene",
        "foam_soft",
        "block_3d",
        "polystyrene foam",
    ),
    _c("packing_foam", "Packing foam", "foam_soft", "block_3d", "foam", unknown=True),
    _c("sponge", "Sponge", "foam_soft", "block_3d", "sponge", unknown=True),
    _c("felt", "Felt", "foam_soft", "soft_sheet", "felt", unknown=True),
    _c(
        "fabric_scrap",
        "Fabric scrap",
        "foam_soft",
        "soft_sheet",
        "fabric",
        unknown=True,
    ),
    _c("denim_scrap", "Denim scrap", "foam_soft", "soft_sheet", "denim"),
    _c(
        "duct_tape",
        "Duct tape",
        "tape_adhesive_tie",
        "roll",
        "tape",
        kind="tape",
        material="other_supported",
        note=_TAPE,
    ),
    _c(
        "masking_tape",
        "Masking tape",
        "tape_adhesive_tie",
        "roll",
        "tape",
        kind="tape",
        material="other_supported",
        note=_TAPE,
    ),
    _c(
        "clear_tape",
        "Clear tape",
        "tape_adhesive_tie",
        "roll",
        "tape",
        kind="tape",
        material="other_supported",
        note=_TAPE,
    ),
    _c("double_sided_tape", "Double-sided tape", "tape_adhesive_tie", "roll", "tape"),
    _c(
        "electrical_tape",
        "Electrical tape",
        "tape_adhesive_tie",
        "roll",
        "stretchy vinyl tape",
    ),
    _c("white_glue", "White glue", "tape_adhesive_tie", "adhesive_container", "glue"),
    _c("glue_stick", "Glue stick", "tape_adhesive_tie", "adhesive_container", "glue"),
    _c(
        "hot_glue_sticks",
        "Hot-glue sticks",
        "tape_adhesive_tie",
        "stick_strip",
        "hot-melt glue",
    ),
    _c(
        "string_twine",
        "String or twine",
        "tape_adhesive_tie",
        "loose_cord",
        "fibre cord",
        unknown=True,
        kind="cord",
        material="other_supported",
        note="Generic tie-joint rules; strength is not tested.",
    ),
    _c(
        "zip_ties",
        "Zip ties",
        "tape_adhesive_tie",
        "small_part",
        "plastic",
        unknown=True,
    ),
    _c(
        "rubber_bands",
        "Rubber bands",
        "connector_metal",
        "small_part",
        "rubber",
        unknown=True,
    ),
    _c(
        "paper_clips",
        "Paper clips",
        "connector_metal",
        "small_part",
        "metal wire",
        unknown=True,
    ),
    _c(
        "binder_clips",
        "Binder clips",
        "connector_metal",
        "small_part",
        "metal",
        unknown=True,
    ),
    _c(
        "aluminum_foil",
        "Aluminium foil",
        "connector_metal",
        "flat_sheet",
        "aluminium foil",
    ),
    _c("wire", "Wire", "connector_metal", "loose_cord", "metal wire", unknown=True),
    _c(
        "nuts_and_bolts",
        "Nuts and bolts",
        "connector_metal",
        "small_part",
        "metal",
        unknown=True,
    ),
)
BY_ID: dict[str, CategoryInfo] = {c.id: c for c in CATALOG}
assert tuple(BY_ID) == CATEGORY_IDS, "catalog order and IDs must match"


Box = Annotated[float, Field(ge=0, le=1)]


class VisibleBox(Record):
    """Approximate, normalised to the photo (0..1). Not a measurement."""

    x1: Box
    y1: Box
    x2: Box
    y2: Box

    @model_validator(mode="after")
    def ordered(self):
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("box corners must be ordered")
        return self


class ItemIdentity(Record):
    """What the object probably is. ``uncertain`` never selects a category."""

    outcome: Literal["catalog", "other", "uncertain"]
    category_id: CategoryId | None = None
    other_label: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    alternatives: tuple[CategoryId, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def consistent(self):
        if self.outcome == "catalog" and self.category_id is None:
            raise ValueError("a catalog outcome names a category")
        if self.outcome != "catalog" and self.category_id is not None:
            raise ValueError("only a catalog outcome selects a category")
        if self.outcome == "other" and self.other_label is None:
            raise ValueError("an other outcome describes the object")
        if self.outcome != "other" and self.other_label is not None:
            raise ValueError("only an other outcome has a free label")
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("alternatives repeat")
        if self.category_id in self.alternatives:
            raise ValueError("the selected category is not its own alternative")
        return self


class ItemProposal(Record):
    """One visible instance proposed by Muse."""

    identity: ItemIdentity
    visible_evidence: Annotated[str, Field(min_length=1, max_length=200)]
    box: VisibleBox | None = None
    visibility: Literal["full", "partial", "unclear"] = "unclear"
    # A pile whose members cannot be told apart is one proposal with
    # ``group_count_unknown``; a count is never invented.
    instance: Literal["single", "group_count_unknown"] = "single"


# Fresh intake responses (intake-items-v2). Bounded so the largest valid answer
# stays small next to the completion budget, leaving room for model reasoning.
MAX_PROPOSED_ITEMS = 12
RecognitionOutcome = Literal["items", "partial", "no_objects"]


class ProposedItem(ItemProposal):
    """``ItemProposal`` with the shorter evidence a fresh response may use."""

    visible_evidence: Annotated[str, Field(min_length=1, max_length=80)]


class IntakeProposal(Record):
    """The provider's whole answer. Every field is required, so a reply with
    only text labels, or with items silently left out, is not accepted.

    ``items``: each visible object is listed. ``partial``: more objects are
    visible than are listed. ``no_objects``: nothing to list, stated
    explicitly. An unidentifiable object is an ``uncertain`` item, never left
    out."""

    recognition: RecognitionOutcome
    items: tuple[ProposedItem, ...] = Field(max_length=MAX_PROPOSED_ITEMS)
    questions: tuple[Annotated[str, Field(min_length=1, max_length=160)], ...] = Field(
        max_length=3
    )

    @model_validator(mode="after")
    def consistent(self):
        if (self.recognition == "no_objects") != (not self.items):
            raise ValueError("no_objects exactly when no item is listed")
        return self


def item_label(identity: ItemIdentity) -> str:
    """Readable name for an identity; never a composition claim."""

    if identity.outcome == "catalog":
        return BY_ID[identity.category_id].label  # type: ignore[index]
    if identity.outcome == "other":
        return identity.other_label  # type: ignore[return-value]
    return "Unidentified object"


class RecognizedItem(Record):
    """A saved, editable card. ``id`` is stable; ``name`` is the display name."""

    id: ID
    name: Annotated[str, Field(min_length=1, max_length=80)]
    identity: ItemIdentity
    identity_source: Literal["muse_suggestion", "user"]
    media_id: ID | None = None
    box: VisibleBox | None = None
    box_source: Literal["muse_approximate", "sam", "user"] | None = None
    visibility: Literal["full", "partial", "unclear"] = "unclear"
    instance: Literal["single", "group_count_unknown"] = "single"
    stock_id: ID | None = None
    # Fields the user edited; later suggestions never change them.
    user_fields: tuple[
        Literal["identity", "name", "box", "visibility", "instance", "stock_id"], ...
    ] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def boxed(self):
        if (self.box is None) != (self.box_source is None):
            raise ValueError("a box has a source")
        if self.box is not None and self.media_id is None:
            raise ValueError("a box belongs to a photo")
        if len(set(self.user_fields)) != len(self.user_fields):
            raise ValueError("user fields repeat")
        return self


class RecognizedInventory(Record):
    items: tuple[RecognizedItem, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def unique(self):
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item IDs repeat")
        stocks = [item.stock_id for item in self.items if item.stock_id]
        if len(set(stocks)) != len(stocks):
            raise ValueError("a stock links to one item")
        return self


def catalog_prompt() -> str:
    """Trusted rules for the fresh intake answer (intake-items-v2)."""
    ids = ", ".join(CATEGORY_IDS)
    return (
        f" Catalog {CATALOG_VERSION}. Return JSON with recognition, items and"
        " questions, nothing else. items has one entry per visible object (at"
        f" most {MAX_PROPOSED_ITEMS}). recognition=items when every visible"
        " object is listed, partial when more are visible than you list, and"
        " no_objects only when the photo shows no object at all (then items is"
        " empty). A pile whose members cannot be told apart is one entry with"
        " instance=group_count_unknown, never an invented count. An object you"
        " cannot identify is still listed, with identity.outcome=uncertain."
        " identity.outcome=catalog only when the photo clearly shows one of"
        f" these category_id values: {ids}. Use outcome=other with a short"
        " other_label for an object outside the catalog; uncertain never"
        " selects a category. Put up to three plausible look-alike categories"
        " in alternatives when appearance is ambiguous. A category is what the"
        " object probably is, not its composition, thickness, strength, mass or"
        " remaining quantity. box is an approximate normalised (0..1) box"
        " around that one object, or null if you cannot place it; never a box"
        " around a printed reference card or marker. visibility=partial when"
        " it is cut off or covered. visible_evidence is a few words naming"
        " what is visible. questions: at most three short ones, only if needed."
        " Be brief."
    )
