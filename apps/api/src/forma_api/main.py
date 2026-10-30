from fastapi import FastAPI

from forma_api.routes.health import router as health_router

app = FastAPI(title="FORMA API", version="0.1.0")
app.include_router(health_router, prefix="/api")
