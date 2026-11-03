"""Supplied resources for a new construction proposal, never stock confirmation.

Authenticated consumers supply their current inventory and reviewed catalogue.
The offline contract itself cannot authenticate user or model claims.
"""

from pydantic import Field, model_validator

from .models import (
    ID,
    Evidence,
    JointProfile,
    Nonnegative,
    Positive,
    Record,
    Stock,
    Text,
    unique,
)


class ConstructionCutProcess(Record):
    kerf_min_mm: Nonnegative | None = None
    edge_margin_min_mm: Nonnegative | None = None
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=64)


class ConstructionJointMaterial(Record):
    joint_id: ID
    profile_id: ID
    stock_id: ID
    length_mm: Positive
    confirmed_accessible: bool | None = None


class ConstructionResources(Record):
    project_id: ID
    inventory_revision_id: ID
    active_version_id: ID | None = None
    stocks: tuple[Stock, ...] = Field(default=(), max_length=64)
    declared_tools: tuple[Text, ...] | None = None
    safe_tools_confirmed: bool = False
    cut_process: ConstructionCutProcess | None = None
    joint_profiles: tuple[JointProfile, ...] = Field(default=(), max_length=32)
    profile_evidence: tuple[Evidence, ...] = Field(default=(), max_length=64)
    joints: tuple[ConstructionJointMaterial, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def identities(self):
        unique(self.stocks, "stock")
        if sum(len(s.usable_regions) for s in self.stocks) > 256:
            raise ValueError("construction allocation supports at most 256 regions")
        unique(tuple(r for s in self.stocks for r in s.usable_regions), "region")
        unique(self.joint_profiles, "profile")
        unique(self.profile_evidence, "profile evidence")
        if len({j.joint_id for j in self.joints}) != len(self.joints):
            raise ValueError("duplicate joint material binding")
        evidence = self.profile_evidence + (
            self.cut_process.evidence if self.cut_process else ()
        )
        if any(e.project_id != self.project_id for e in evidence):
            raise ValueError("resource evidence belongs to another project")
        return self
