"""MCP endpoint so an agent can upload a user's project data through the API.

Each tool forwards to the existing REST route in-process with the caller's
bearer token, so authentication, validation, idempotency and stale-revision
checks stay in one place. Tools cover reading, project creation, photo upload
and inventory confirmation only: provider calls, plan approval, physical
records and deletion need the user in the app.
"""

import base64
import binascii
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Any, Literal

import httpx2
from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from forma_api.media import MAX_PHOTO_BYTES, Media, MediaList
from forma_api.projects import (
    InventoryUpdate,
    Key,
    Project,
    ProjectResult,
    SavedProjectList,
)
from forma_domain.models import ID, ErrorEnvelope, Text

MCP_PATH = "/api/mcp"
# Base64 inflates a maximum-size photo by a third; leave room for the JSON-RPC
# envelope so the photo route, not the transport, enforces the photo limit.
MAX_MCP_BODY_BYTES = MAX_PHOTO_BYTES * 4 // 3 + 64 * 1024

INSTRUCTIONS = """\
FORMA turns measured reused materials into a small tabletop fixture.
Use these tools to save what the user tells you: the goal, photos of their
materials and the measured inventory. Unknown measurements stay unknown: send
value null with source "unknown" instead of guessing. Only call
update_inventory with user_confirmed true after the user has reviewed the
values. Reuse the same idempotency_key when retrying a call; use a new one
for a new request. Plans, approvals and build records are made in the app."""


class _Endpoint:
    """Checks the owner token, then hands the request to the running SDK app.

    The SDK's session manager runs only once, so each app lifespan builds a
    fresh SDK app behind this stable route.
    """

    def __init__(self, server: MCPServer, lookup: Callable[[str], str | None]):
        self.server = server
        self.lookup = lookup
        self.app: ASGIApp | None = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        # Bearer tokens already stop DNS-rebinding pages, and the hosted Host
        # header is not localhost, so the SDK's localhost-only check is off.
        app = self.server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            max_request_body_size=MAX_MCP_BODY_BYTES,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        async with self.server.session_manager.run():
            self.app = app
            try:
                yield
            finally:
                self.app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or self.lookup(token) is None:
            envelope = ErrorEnvelope(
                code="forbidden", message="A configured bearer credential is required"
            )
            response = JSONResponse(
                envelope.model_dump(mode="json"),
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        if self.app is None:
            raise RuntimeError("The MCP endpoint needs the app lifespan running")
        await self.app(scope, receive, send)


def _server(api: FastAPI) -> MCPServer:
    # The SDK configures root logging at this level; INFO would log every
    # in-process API request.
    server = MCPServer(
        "forma", instructions=INSTRUCTIONS, version=api.version, log_level="WARNING"
    )

    async def call(
        ctx: Context, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        headers = {
            "Authorization": ctx.request_context.request.headers["authorization"],
            **kwargs.pop("headers", {}),
        }
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=api), base_url="http://forma"
        ) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
        if response.is_success:
            return response.json()
        try:
            envelope = ErrorEnvelope.model_validate(response.json())
            detail = f"{envelope.code}: {envelope.message}"
        except ValueError:
            detail = response.text
        raise ToolError(f"FORMA API returned {response.status_code} ({detail})")

    @server.tool(annotations={"readOnlyHint": True})
    async def list_projects(
        ctx: Context,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        cursor: ID | None = None,
    ) -> SavedProjectList:
        """List the caller's saved projects, oldest first. Pass next_cursor to page."""
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return SavedProjectList.model_validate(
            await call(ctx, "GET", "/api/projects", params=params)
        )

    @server.tool(annotations={"readOnlyHint": True})
    async def get_project(ctx: Context, project_id: ID) -> Project:
        """Read one project: goal, inventory revision, stocks and requirements."""
        return Project.model_validate(
            await call(ctx, "GET", f"/api/projects/{project_id}")
        )

    @server.tool(annotations={"destructiveHint": False, "idempotentHint": True})
    async def create_project(
        ctx: Context, goal: Text, idempotency_key: Key
    ) -> ProjectResult:
        """Create a project for the user's goal, such as a phone stand."""
        return ProjectResult.model_validate(
            await call(
                ctx,
                "POST",
                "/api/projects",
                json={"goal": goal, "idempotency_key": idempotency_key},
            )
        )

    @server.tool(annotations={"readOnlyHint": True})
    async def list_photos(ctx: Context, project_id: ID) -> MediaList:
        """List the project's private photo metadata, including unlinked uploads."""
        return MediaList.model_validate(
            await call(ctx, "GET", f"/api/projects/{project_id}/media")
        )

    @server.tool(annotations={"destructiveHint": False, "idempotentHint": True})
    async def upload_photo(
        ctx: Context,
        project_id: ID,
        content_type: Literal["image/jpeg", "image/png", "image/webp"],
        image_base64: str,
        idempotency_key: Key,
    ) -> Media:
        """Store a private photo of the user's materials (at most 8 MiB).

        Returns the media ID to list in a stock's image_ids. Storing a photo
        sends it to no model and does not measure anything.
        """
        try:
            body = base64.b64decode(image_base64, validate=True)
        except binascii.Error as error:
            raise ToolError("image_base64 is not valid base64") from error
        result = await call(
            ctx,
            "POST",
            f"/api/projects/{project_id}/media",
            content=body,
            headers={"Content-Type": content_type, "Idempotency-Key": idempotency_key},
        )
        return Media.model_validate(result["media"])

    # Replaces the saved stock list, so clients should confirm it.
    @server.tool(annotations={"destructiveHint": True, "idempotentHint": True})
    async def update_inventory(
        ctx: Context, project_id: ID, inventory: InventoryUpdate
    ) -> ProjectResult:
        """Replace the project's material inventory and optional requirements.

        Send the project's current revision_id as expected_revision_id; a stale
        revision is rejected. Omitting requirements keeps the saved ones, and
        null clears them. Only set user_confirmed after the user reviewed the
        values.
        """
        payload = inventory.model_dump(
            mode="json",
            exclude=set()
            if "requirements" in inventory.model_fields_set
            else {"requirements"},
        )
        return ProjectResult.model_validate(
            await call(
                ctx, "PUT", f"/api/projects/{project_id}/inventory", json=payload
            )
        )

    return server


def mount_mcp(
    api: FastAPI, lookup: Callable[[str], str | None]
) -> Callable[[], AbstractAsyncContextManager[None]]:
    """Adds the MCP route; enter the returned context in the app lifespan."""
    endpoint = _Endpoint(_server(api), lookup)
    api.add_route(MCP_PATH, endpoint)
    return endpoint.running
