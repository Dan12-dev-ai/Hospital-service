"""Runs the real hospital service for the browser tests.

Started by playwright.config.ts with backend-hospital as the working
directory and HOSPITAL_DATABASE_URL pointing at a throwaway SQLite file:
creates the tables in that fresh database, then serves the API.

    python ../frontend-hospital-portal/e2e/backend.py <port>
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

import uvicorn  # noqa: E402

from app import db  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8120
    url = os.environ.get("HOSPITAL_DATABASE_URL", "")
    if not url.startswith("sqlite:///"):
        raise SystemExit("The browser tests need a throwaway SQLite HOSPITAL_DATABASE_URL.")
    db.create_all()
    # The portal API and, beside it, the integrations service (separate in
    # production: app/integrations_main.py), so the tests reach both on one port.
    from app import integrations_main
    from app.main import create_app

    app = create_app()
    app.mount("/", integrations_main.create_app())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
