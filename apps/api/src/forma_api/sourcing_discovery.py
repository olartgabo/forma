"""Bounded automatic map discovery followed by public retailer price evidence."""

from forma_api.model_gateway import GatewayError
from forma_api.sourcing_location import (
    LocationServiceError,
    NearbyRequest,
    nearby_places,
)


class NearbyMetaGateway:
    """Keep mapped shops separate while Meta researches cited retail offers."""

    def __init__(self, meta_gateway, places_fetch=nearby_places):
        self.meta_gateway = meta_gateway
        self.places_fetch = places_fetch
        self.places = ()
        self.message = None

    def research(self, request):
        try:
            result = self.places_fetch(
                NearbyRequest(
                    location=request.location,
                    radius_m=request.radius_m,
                    category=request.category,
                )
            )
        except LocationServiceError:
            self.message = (
                "Nearby map lookup was unavailable. Meta is researching the "
                "confirmed area; nearby branches and stock remain unverified."
            )
        except Exception as exc:
            # No generation has started. An unexpected map adapter failure must
            # stay visible rather than being mistaken for unknown Meta billing.
            raise GatewayError("discovery_failed") from exc
        else:
            self.places = result.places
            self.message = result.message
        # Do not wrap paid-provider exceptions: PendingResearch and uncertain
        # outcomes must retain their identity, usage and reservation semantics.
        return self.meta_gateway.research(request, places=self.places)


class NearbyDiscoveryGateway:
    def __init__(self, places_fetch=nearby_places, offers_fetch=None):
        self.places_fetch = places_fetch
        self.offers_fetch = offers_fetch
        self.places = ()
        self.message = None

    def research(self, request):
        try:
            result = self.places_fetch(
                NearbyRequest(
                    location=request.location,
                    radius_m=request.radius_m,
                    category=request.category,
                )
            )
            self.places = result.places
            self.message = result.message
            websites = tuple(
                dict.fromkeys(place.website for place in result.places if place.website)
            )
            if not websites:
                self.message += " No mapped retailer websites are available for automatic price research."
                return (), None
            if self.offers_fetch is None:
                from forma_api.retail_evidence import discover_offers

                offers_fetch = discover_offers
            else:
                offers_fetch = self.offers_fetch
            offers = tuple(offers_fetch(request.item, request.currency, websites))[:5]
            if not offers:
                self.message += " No matching published price was verified on the discovered retailer websites."
            return offers, None
        except Exception as exc:
            # This path never generates a paid model response. A public lookup
            # failure is a known failed research run, not unknown model billing.
            raise GatewayError("discovery_failed") from exc
