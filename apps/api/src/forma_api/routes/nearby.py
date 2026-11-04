"""Owner-scoped, explicit-location read-only map research."""

from typing import Annotated

from fastapi import APIRouter, Depends

from forma_api.projects import ProjectStore
from forma_api.routes.sourcing import SourcingError, SourcingRoute
from forma_api.sourcing_location import (
    LocationReverseRequest,
    LocationReverseResponse,
    LocationSearchRequest,
    LocationSearchResponse,
    LocationServiceError,
    NearbyRequest,
    NearbyResponse,
    geocode_city,
    nearby_places,
    reverse_location,
)
from forma_domain.models import ID


def nearby_router(
    store: ProjectStore, authenticate, geocode=None, discover=None, reverse=None
):
    Owner = Annotated[str, Depends(authenticate)]
    router = APIRouter(tags=["sourcing"], route_class=SourcingRoute)

    def authorized(owner, project_id):
        with store.transaction() as connection:
            store.read(connection, owner, project_id)

    @router.post(
        "/{project_id}/sourcing/locations", response_model=LocationSearchResponse
    )
    def locations(project_id: ID, body: LocationSearchRequest, owner: Owner):
        authorized(owner, project_id)
        if not body.transfer_consented:
            raise SourcingError(
                422,
                "consent_required",
                "Consent to send this city to OpenStreetMap is required.",
            )
        try:
            return (geocode or geocode_city)(body.city)
        except LocationServiceError as exc:
            raise SourcingError(503, "location_unavailable", str(exc)) from None

    @router.post("/{project_id}/sourcing/nearby", response_model=NearbyResponse)
    def nearby(project_id: ID, body: NearbyRequest, owner: Owner):
        authorized(owner, project_id)
        try:
            return (discover or nearby_places)(body)
        except LocationServiceError as exc:
            raise SourcingError(503, "location_unavailable", str(exc)) from None

    @router.post(
        "/{project_id}/sourcing/reverse", response_model=LocationReverseResponse
    )
    def reverse_point(project_id: ID, body: LocationReverseRequest, owner: Owner):
        authorized(owner, project_id)
        try:
            return (reverse or reverse_location)(body.location)
        except LocationServiceError as exc:
            raise SourcingError(503, "location_unavailable", str(exc)) from None

    return router
