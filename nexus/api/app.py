"""NEXUS API application."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexus.core.errors import NexusError
from nexus.core.logging_setup import get_logger, setup_logging
from nexus.db.session import check_db, init_db

setup_logging()
log = get_logger("nexus.api")


def create_app() -> FastAPI:
    app = FastAPI(
        title="NEXUS API",
        description="Autonomous Intelligence & Decision Engine - Ethereum intelligence platform",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NexusError)
    async def nexus_error_handler(request: Request, exc: NexusError):
        status = 404 if exc.code == "not_found" else 400
        return JSONResponse(
            status_code=status,
            content={"error": exc.code, "message": str(exc), "details": exc.details},
        )

    from nexus.api.routers import (
        alerts,
        automations,
        entities,
        evaluations,
        events,
        investigations,
        metrics,
        mlops,
        overview,
        scores,
        system,
    )

    for router in (
        overview.router, entities.router, events.router,
        investigations.router, alerts.router, automations.router,
        evaluations.router, mlops.router, metrics.router, system.router,
        scores.router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        log.info("NEXUS API ready (db ok=%s)", check_db())

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "db": check_db()}

    return app


app = create_app()
