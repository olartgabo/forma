"""Ephemeral provider credentials scoped to one HTTP request."""

import os
from contextvars import ContextVar

from starlette.responses import JSONResponse

_request_key: ContextVar[str | None] = ContextVar("forma_model_key", default=None)


def model_api_key() -> str:
    key = _request_key.get()
    return key if key is not None else os.environ.get("MODEL_API_KEY", "")


class ProviderCredentialMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        keys = [v for k, v in scope["headers"] if k.lower() == b"x-forma-model-key"]
        if keys and (
            len(keys) != 1
            or not 1 <= len(keys[0]) <= 4096
            or any(byte < 33 or byte > 126 for byte in keys[0])
        ):
            return await JSONResponse(
                {"detail": "Invalid model credential header"}, status_code=400
            )(scope, receive, send)
        token = _request_key.set(keys[0].decode("ascii") if keys else None)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_key.reset(token)
