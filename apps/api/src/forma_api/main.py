import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from forma_api.mcp_server import mount_mcp
from forma_api.projects import (
    ProjectError,
    ProjectStore,
    owner_lookup,
    project_error_handler,
    project_router,
)
from forma_api.routes.health import router as health_router
from forma_api.routes.photo_estimates import reference_router


def create_app(
    data_dir: Path | None = None, credentials: dict[str, str] | None = None
) -> FastAPI:
    if credentials is None:
        credentials = json.loads(os.environ.get("FORMA_API_TOKENS", "{}"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with run_mcp():
            yield

    app = FastAPI(title="FORMA API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(ProjectError, project_error_handler)
    app.include_router(health_router, prefix="/api")
    app.include_router(reference_router, prefix="/api")
    app.include_router(
        project_router(
            ProjectStore(
                data_dir or Path(os.environ.get("FORMA_DATA_DIR", ".local/forma"))
            ),
            credentials,
        ),
        prefix="/api",
    )
    run_mcp = mount_mcp(app, owner_lookup(credentials))
    return app


app = create_app()
