import json
import os
from pathlib import Path

from fastapi import FastAPI

from forma_api.projects import (
    ProjectError,
    ProjectStore,
    project_error_handler,
    project_router,
)
from forma_api.routes.health import router as health_router


def create_app(
    data_dir: Path | None = None, credentials: dict[str, str] | None = None
) -> FastAPI:
    app = FastAPI(title="FORMA API", version="0.1.0")
    app.add_exception_handler(ProjectError, project_error_handler)
    app.include_router(health_router, prefix="/api")
    app.include_router(
        project_router(
            ProjectStore(
                data_dir or Path(os.environ.get("FORMA_DATA_DIR", ".local/forma"))
            ),
            credentials
            if credentials is not None
            else json.loads(os.environ.get("FORMA_API_TOKENS", "{}")),
        ),
        prefix="/api",
    )
    return app


app = create_app()
