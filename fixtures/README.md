# Fixtures

Owners: @ResniDev for domain/compiler cases; @olartgabo for measured inventories
and evaluation evidence. Status: no JSON fixtures exist yet.

Reserve these spec-defined cases once contracts exist:

| File to create          | Required content                                                |
| ----------------------- | --------------------------------------------------------------- |
| inventory_A.json        | Confirmed inventory A, or explicitly synthetic contract fixture |
| inventory_B.json        | Meaningfully different inventory with provenance                |
| missing_connector.json  | Supported connector loss or honest no-repair outcome            |
| damaged_slot.json       | Damaged geometry, actual remaining stock, affected checks       |
| size_mismatch.json      | Confirmed dimension discrepancy, irreversible-work constraints  |
| impossible_request.json | Concrete infeasible stock/geometry/domain case                  |

Never fabricate measured values to complete this list. Synthetic fixtures must
be labeled and linked to expected compiler results. Physical evidence needs
consent/redaction and links to [build logs](../data/physical-tests/README.md).
Add further negative cases for duplicate stock, unsupported operations and stale checkpoints.
