from pydantic import Field

from forma_domain.models import Evidence, Nonnegative, Record


class CutProcess(Record):
    """Measured cutting limits; fixture evidence is opt-in and never physical proof."""

    kerf_min_mm: Nonnegative
    edge_margin_min_mm: Nonnegative
    evidence: tuple[Evidence, ...] = Field(min_length=1)

    def verified(self, *, allow_synthetic: bool) -> bool:
        return all(
            (
                (e.verification_state == "user_confirmed" and e.provenance == "user")
                or (allow_synthetic and e.provenance == "synthetic_fixture")
            )
            and e.kind in ("measurement", "physical_test")
            for e in self.evidence
        )
