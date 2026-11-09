"""MORVIX FastAPI entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import config
from backend.app.database import database_ready, initialize_database
from backend.app.api import auth, extension, parent
from backend.app.classifiers import classifier_diagnostics, classifier_readiness

DASHBOARD_DIR = config.ROOT / "web_dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MORVIX API",
        description="Local parent dashboard, extension policy, event history, and local classification API.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_origin_regex=r"chrome-extension://[a-p]{32}",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth.router)
    app.include_router(parent.router)
    app.include_router(extension.router)
    if DASHBOARD_DIR.exists():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR), name="dashboard-assets")

    @app.get("/api/v1/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": "morvix-api"}

    @app.get("/api/v1/health/ready", tags=["health"])
    def ready():
        db_ready = database_ready()
        return {
            "status": "ready" if db_ready else "degraded",
            "database": "ready" if db_ready else "unavailable",
            "classifiers": classifier_readiness(),
            "classifier_details": classifier_diagnostics(),
            "note": "Backend readiness does not imply that local classifiers are initialized or able to infer.",
        }

    @app.get("/", include_in_schema=False)
    def dashboard():
        index = Path(DASHBOARD_DIR) / "index.html"
        if not index.exists():
            return {"service": "MORVIX API", "docs": "/docs"}
        return FileResponse(index)

    return app


app = create_app()

