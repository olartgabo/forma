"""Advisory sourcing contracts. Research never establishes physical stock."""

import ipaddress
import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, field_validator, model_validator

from forma_api.sourcing_location import Category, ConfirmedLocation, NearbyPlace
from forma_domain.models import ID, Record


class SourcingNeed(Record):
    id: ID

    label: str

    kind: Literal["material", "tool"]

    origin: Literal["engine"] = "engine"

    reason: str


class SourcingNeeds(Record):
    pending_run_id: ID | None = None

    project_id: ID

    revision_id: ID

    active_version_id: ID | None = None

    needs: tuple[SourcingNeed, ...] = ()

    guidance: tuple[str, ...] = ()

    marketplace_status: Literal["authorization_required"] = "authorization_required"


class ResearchRequest(Record):
    expected_revision_id: ID

    idempotency_key: str = Field(min_length=8, max_length=128)

    item: str = Field(min_length=1, max_length=200)

    area: str = Field(min_length=1, max_length=120)

    currency: str = Field(pattern=r"^[A-Z]{3}$")

    provider_transfer_consented: StrictBool = False

    source: Literal["suppliers", "marketplace", "supplier_page"] = "suppliers"

    supplier_url: str | None = Field(default=None, max_length=2000)

    location: ConfirmedLocation | None = None

    radius_m: int = Field(default=5000, ge=100, le=10000)

    category: Category = "hardware"

    @model_validator(mode="after")
    def source_url(self):
        if self.location is not None and self.source != "suppliers":
            raise ValueError("Nearby discovery applies only to supplier research")
        if self.source == "supplier_page":
            from forma_api.supplier_page import supported_supplier_url

            if not self.supplier_url or not supported_supplier_url(self.supplier_url):
                raise ValueError("Use a supported supplier HTTPS product URL")
        elif self.supplier_url is not None:
            raise ValueError("A supplier URL applies only to supplier_page")
        return self

    @field_validator("item", "area", "idempotency_key")
    @classmethod
    def nonblank(cls, value):

        if not value.strip():
            raise ValueError("A value is required")

        return value.strip()


class OfferObservation(Record):
    title: str = Field(min_length=1, max_length=200)

    url: str = Field(max_length=2000)

    price: str | None = None

    currency: str = Field(pattern=r"^[A-Z]{3}$")

    price_status: Literal[
        "listed", "listed_free", "price_unknown", "price_conflict", "partial_price"
    ]

    availability: str = Field(default="Unconfirmed", max_length=200)

    location: str = Field(default="Unknown", max_length=200)

    notes: str = Field(default="", max_length=600)


class SourcingUsage(Record):
    search_queries: int | None = Field(default=None, ge=0)

    input_tokens: int | None = Field(default=None, ge=0)

    output_tokens: int | None = Field(default=None, ge=0)


class SupplierSearchOffer(Record):
    """Required provider proposal fields; no authority beyond source claims."""

    title: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)
    price: str | None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price_status: Literal[
        "listed", "listed_free", "price_unknown", "price_conflict", "partial_price"
    ]
    availability: str = Field(max_length=200)
    location: str = Field(max_length=200)
    notes: str = Field(max_length=600)


class SupplierSearchOutput(Record):
    offers: tuple[SupplierSearchOffer, ...] = Field(max_length=5)


class ResearchRun(Record):
    # Old receipts remain Meta runs unless their original producer recorded otherwise.
    kind: Literal["meta", "public_discovery", "supplier_page"] = "meta"

    nearby_places: tuple[NearbyPlace, ...] = Field(default=(), max_length=10)

    discovery_message: str | None = None

    provider_response_id: str | None = Field(default=None, max_length=165)

    id: ID

    project_id: ID

    revision_id: ID

    status: Literal[
        "running", "succeeded", "no_verified_results", "failed", "outcome_unknown"
    ]

    offers: tuple[OfferObservation, ...] = Field(default=(), max_length=5)

    usage: SourcingUsage | None = None

    error: str | None = None

    replayed: bool = False

    active_version_id: ID | None = None

    observed_at: str

    item: str

    area: str

    currency: str


class SourcingErrorResponse(Record):
    code: str

    message: str


def permitted_url(value: str) -> bool:

    try:
        parsed = urlsplit(value)

        host = (parsed.hostname or "").lower().rstrip(".")

        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return False

        if (
            not host
            or "." not in host
            or host.endswith((".local", ".localhost", ".internal"))
        ):
            return False

        if any(
            host == blocked or host.endswith("." + blocked)
            for blocked in ("facebook.com", "fb.com", "fb.me", "meta.ai", "localhost")
        ):
            return False

        try:
            ipaddress.ip_address(host)

            return False

        except ValueError:
            return True

    except ValueError:
        return False


def price_status(price: str | None, text: str) -> tuple[str | None, str]:

    lowered = text.casefold()

    if price is not None and (not isinstance(price, str) or len(price) > 40):
        return None, "price_unknown"

    if re.search(
        r"\bdm\b|\binbox\b|consultar|al privado|contact.*price|ask.*price|price.*request",
        lowered,
    ):
        return None, "price_unknown"

    currency_amount = r"(?:(?:[a-z]{3}|bs\.?|us|ca|au|nz|c|a)\s*)?(?:[$€£¥]\s*)?\d"
    if re.search(
        r"deposit|installment|cuota|desde|\bstarting\s+(?:at\b|from\b|[$€£¥]|(?:usd|bob|bs\.?)\s*\d|\d)",
        lowered,
    ) or re.search(r"\bfrom\s*" + currency_amount, lowered):
        return None, "partial_price"

    try:
        amount = Decimal(price) if price is not None else None

        if (
            amount is None
            or not amount.is_finite()
            or amount < 0
            or amount > Decimal("1000000000")
        ):
            return None, "price_unknown"

    except (InvalidOperation, TypeError):
        return None, "price_unknown"

    if amount == 0:
        if re.search(
            r"free\s+(?:shipping|delivery)|(?:shipping|delivery)\s+(?:is\s+)?free|(?:env[ií]o|entrega)\s+gratis|gratis\s+(?:env[ií]o|entrega)",
            lowered,
        ):
            return None, "price_unknown"

        if re.search(r"giveaway|free to collect|gratis|regalo", lowered):
            return "0", "listed_free"

        return None, "price_unknown"

    return format(amount, "f"), "listed"
