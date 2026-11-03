"""Material-bound targets and general panel topologies share the existing engine."""

import pytest
from forma_stability.lab_construction import run_generation


def request(kind="enclosure", sides=5):
    return {
        "shape": {
            "kind": kind,
            "width_mm": 300,
            "depth_mm": 240,
            "height_mm": 140,
            "sides": sides,
        }
    }


@pytest.mark.parametrize("kind", ["polygon", "enclosure", "screen"])
@pytest.mark.parametrize("sides", [3, 5, 8, 12])
def test_generated_topologies_not_fixed_stage_lists(kind, sides):
    result = run_generation(request(kind, sides))
    plan = result["construction"]
    count = 1 if kind == "polygon" else sides
    joins = sides if kind == "enclosure" else count - 1
    assert len(plan["piece_catalog"]) == count
    assert len(plan["steps"]) == count + joins + 1
    assert all(not step["analysis"]["physical_evidence_ids"] for step in plan["steps"])
    if kind != "polygon":
        assert all(p["geometry_class"] == "rectangle" for p in plan["piece_catalog"])
        assert plan["steps"][-1]["unresolved_predicates"]
    facets = plan["steps"][-1]["analysis"]["facets"]
    for axis, extent in [("x", 0.3), ("y", 0.24)]:
        values = [p[axis] for f in facets for p in f["vertices"]]
        assert max(values) - min(values) == pytest.approx(extent)


def test_local_real_materials_missing_process_is_blocked_and_mass_not_invented():
    payload = request("box")
    payload["resources"] = {
        "project_id": "my-project",
        "inventory_revision_id": "my-stock-revision",
        "stocks": [],
    }
    result = run_generation(payload)
    assert result["fabrication_basis"] == "supplied_materials_unverified"
    assert result["fabrication_blockers"]
    target = result["construction"]["request"]["target"]
    assert target["assembly"]["project_id"] == "my-project"
    assert target["snapshot"]["inventory_revision"] == "my-stock-revision"
    assert all(p["mass_kg"] is None for p in target["snapshot"]["parts"])
    assert result["fabrication_plan"] is None
    assert run_generation(result)["construction"] == result["construction"]
    payload["synthetic_fabrication"] = True
    with pytest.raises(ValueError, match="cannot be mixed"):
        run_generation(payload)


def test_model_piece_names_are_referenced_but_never_promoted_to_geometry_truth():
    payload = request("polygon")
    payload["piece_annotations"] = [
        {
            "part_id": "panel",
            "display_name": "Shelf insert",
            "role": "base",
            "source": "model",
            "proposed_classification": "steel cylinder",
        }
    ]
    result = run_generation(payload)
    piece = result["construction"]["piece_catalog"][0]
    assert piece["geometry_class"] == "convex_polygon"
    assert piece["annotation"]["proposed_classification"] == "steel cylinder"
    assert piece["display_name"] == "Shelf insert"
    assert piece["reference"] in result["construction"]["steps"][0]["instruction"]
    assert run_generation(result)["construction"] == result["construction"]


def test_polygon_not_silently_manufactured_as_rectangle():
    payload = request("polygon") | {"synthetic_fabrication": True}
    result = run_generation(payload)
    assert result["fabrication_plan"] is None
    assert result["fabrication_blockers"]


@pytest.mark.parametrize("kind", ["screen", "enclosure"])
def test_rectangular_wall_topologies_use_gabo_operations(kind):
    payload = request(kind, 3) | {"synthetic_fabrication": True}
    result = run_generation(payload)
    assert result["fabrication_report"]["status"] == "ready"
    assert len(
        [
            op
            for op in result["fabrication_plan"]["operations"]
            if op["type"] == "tape_joint"
        ]
    ) == (3 if kind == "enclosure" else 2)
    assert result["construction"]["steps"][-1]["unresolved_predicates"]
