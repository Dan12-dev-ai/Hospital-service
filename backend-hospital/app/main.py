"""The hospital service API (run with ``uvicorn app.main:app``)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api import (
    admin, application, auth, bookings, doctors, history, imports, onboarding, patients, queue, shared,
)
from app.config import Settings, get_settings

logger = logging.getLogger("hospital")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Endod Hospital Service",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    if "*" in settings.CORS_ORIGINS and settings.is_production:
        raise RuntimeError("HOSPITAL_CORS_ORIGINS must list exact origins in production.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        # Sessions travel in the Authorization header, never in cookies.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Filename"],
    )

    # One error shape everywhere: {"error": "...", "error_code": "..."}.
    # Starlette's HTTPException is the base of FastAPI's, so this also covers
    # routing errors such as 404 for an unknown path and 405.
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(status_code=exc.status_code, headers=getattr(exc, "headers", None),
                            content={"error": message, "error_code": f"HTTP_{exc.status_code}"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
        return JSONResponse(status_code=422, content={
            "error": f"{field}: {first.get('msg', 'invalid value')}", "error_code": "VALIDATION_ERROR",
            "details": [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
                        for e in exc.errors()],
        })

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.exception("unhandled_error path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"error": "Internal server error.", "error_code": "INTERNAL"})

    @app.get("/health", tags=["service"])
    def health():
        return {"status": "ok", "service": "hospital"}

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(patients.router)
    app.include_router(doctors.router)
    app.include_router(bookings.router)
    app.include_router(onboarding.router)
    app.include_router(application.router)
    app.include_router(history.router)
    app.include_router(history.platform_router)
    app.include_router(queue.router)
    app.include_router(shared.router)
    app.include_router(imports.router)
    return app


app = create_app()
