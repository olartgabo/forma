from collections import Counter

import pytest
from pydantic import ValidationError

from forma_domain.material_catalog import (
    BY_ID,
    CAPABILITY_FOR_FORM,
    CAPABILITY_TEXT,
    CATALOG,
    CATEGORY_IDS,
    ItemIdentity,
    ItemProposal,
    RecognizedInventory,
    RecognizedItem,
    catalog_prompt,
)


def test_catalog_has_the_48_requested_categories_in_six_groups():
    assert len(CATALOG) == len(set(CATEGORY_IDS)) == 48
    assert Counter(c.group for c in CATALOG) == {
        "paper_cardboard": 8,
        "wood_plant": 8,
        "plastic": 8,
        "foam_soft": 8,
        "tape_adhesive_tie": 10,
        "connector_metal": 6,
    }
    assert set(CAPABILITY_FOR_FORM.values()) == set(CAPABILITY_TEXT)
    assert all(c.form in CAPABILITY_FOR_FORM for c in CATALOG)


def test_only_existing_build_rules_link_to_stock():
    linked = {c.id: (c.stock_kind, c.stock_material) for c in CATALOG if c.stock_kind}
    assert linked == {
        "corrugated_cardboard": ("sheet", "cardboard"),
        "thin_packaging_card": ("sheet", "paperboard"),
        "cardstock": ("sheet", "paperboard"),
        "duct_tape": ("tape", "other_supported"),
        "masking_tape": ("tape", "other_supported"),
        "clear_tape": ("tape", "other_supported"),
        "string_twine": ("cord", "other_supported"),
    }
    # Recognised but not supported: never forced into cardboard or a generic.
    for cid in ("plastic_bottle", "food_container", "printer_paper", "foam_board"):
        assert BY_ID[cid].support == "build_rules_not_available"
        assert BY_ID[cid].stock_material is None
    assert BY_ID["food_container"].composition_unknown


def test_measurement_capability_follows_visible_form():
    cap = {c.id: CAPABILITY_FOR_FORM[c.form] for c in CATALOG}
    assert cap["corrugated_cardboard"] == "planar_outline"
    assert cap["craft_sticks"] == "length_and_width"
    assert cap["foam_board"] == "planar_outline_top_face"
    assert cap["felt"] == "planar_outline_as_laid"
    for cid in ("paper_tube", "plastic_bottle", "paper_cup", "pvc_pipe", "sponge"):
        assert cap[cid] == "ruler_or_more_views"
    for cid in ("duct_tape", "glue_stick", "white_glue", "string_twine", "wire"):
        assert cap[cid] == "no_quantity_from_photo"


@pytest.mark.parametrize(
    "identity",
    [
        {"outcome": "catalog"},
        {"outcome": "uncertain", "category_id": "felt"},
        {"outcome": "other"},
        {"outcome": "catalog", "category_id": "felt", "other_label": "x"},
        {"outcome": "catalog", "category_id": "felt", "alternatives": ["felt"]},
        {"outcome": "uncertain", "alternatives": ["felt", "felt"]},
        {"outcome": "catalog", "category_id": "titanium_plate"},
        {
            "outcome": "uncertain",
            "alternatives": ["felt", "sponge", "cork_sheet", "cardstock"],
        },
    ],
)
def test_identity_rejects_forced_or_inconsistent_selection(identity):
    with pytest.raises(ValidationError):
        ItemIdentity.model_validate(identity)


def test_uncertain_and_other_are_valid_without_a_category():
    assert ItemIdentity(outcome="uncertain", alternatives=("felt", "fabric_scrap"))
    assert ItemIdentity(outcome="other", other_label="ceramic mug")
    assert ItemIdentity(
        outcome="catalog",
        category_id="cardstock",
        alternatives=("thin_packaging_card",),
    )


def test_provider_json_is_constrained_to_the_catalog():
    good = (
        '{"identity":{"outcome":"catalog","category_id":"plastic_bottle"},'
        '"visible_evidence":"clear bottle with a cap",'
        '"box":{"x1":0.1,"y1":0.2,"x2":0.3,"y2":0.9},"visibility":"partial",'
        '"instance":"single"}'
    )
    item = ItemProposal.model_validate_json(good, strict=True)
    assert item.identity.category_id == "plastic_bottle"
    with pytest.raises(ValidationError):
        ItemProposal.model_validate_json(good.replace("plastic_bottle", "pet"))
    with pytest.raises(ValidationError):
        ItemProposal.model_validate_json(good.replace('"x2":0.3', '"x2":0.05'))
    with pytest.raises(ValidationError):  # no quantities in the contract
        ItemProposal.model_validate_json(good[:-1] + ',"count":12}')


def test_saved_items_keep_identity_and_link_one_stock():
    item = RecognizedItem(
        id="bottle--1",
        name="Water bottle",
        identity=ItemIdentity(outcome="catalog", category_id="plastic_bottle"),
        identity_source="user",
        user_fields=("identity",),
    )
    with pytest.raises(ValidationError):
        RecognizedItem.model_validate(
            {**item.model_dump(), "box": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}}
        )
    linked = {**item.model_dump(), "stock_id": "sheet-a"}
    with pytest.raises(ValidationError):
        RecognizedInventory.model_validate(
            {"items": [linked, {**linked, "id": "bottle--2"}]}
        )
    with pytest.raises(ValidationError):
        RecognizedInventory.model_validate({"items": [item, item]})


def test_prompt_lists_every_category_and_the_abstain_rules():
    prompt = catalog_prompt()
    assert all(cid in prompt for cid in CATEGORY_IDS)
    for phrase in ("outcome=uncertain", "outcome=other", "never an invented count"):
        assert phrase in prompt
