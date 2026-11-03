"""The browser consumes the same stability contract as the Python boundary."""

import json

from forma_domain.generate import artifacts


def test_stability_contracts_are_exported_from_pydantic():
    outputs = artifacts()
    schema = json.loads(outputs["packages/domain/generated/contracts.schema.json"])
    api = json.loads(outputs["packages/domain/generated/openapi.json"])
    browser = outputs["apps/web/src/lib/generated/contracts.ts"]
    for name in ("AnalysisIdentity", "QuantityEstimate", "StabilityReport"):
        assert name in schema["$defs"]
        assert name in api["components"]["schemas"]
        assert f"export type {name} =" in browser
    assert schema["$defs"]["StabilityReport"]["additionalProperties"] is False
    assert "BuildPlan" in schema["$defs"]
