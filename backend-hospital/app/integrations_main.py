"""The integrations service: ``uvicorn app.integrations_main:app``.

The integration API for hospitals' own systems (app/api/integrations.py,
under /integrations/v1) and /health, nothing else: the only service on the
shared edge network (nginx reaches it as ``endod-hospital-integrations``), and
the only one with the token signing key, so a missing key stops only the
integration API. It connects to the database as the app role, like the API.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import integrations
from app.crypto import check_master_key, verify_master_key
from app.db import check_connection_role
from app.integrations import signing


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_master_key()
    check_connection_role()
    verify_master_key()
    # Without its signing key the integration API answers 503 (outside development and test).
    signing.check_at_start()
    yield


def create_app() -> FastAPI:
    check_master_key()
    app = FastAPI(title="Endod Hospital Integrations", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": "hospital-integrations"}

    app.mount(integrations.PREFIX, integrations.create_app())
    return app


app = create_app()
