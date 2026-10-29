"""Settings, read from the environment (prefix ``HOSPITAL_``) or ``.env``."""

from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOSPITAL_", env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    #: SQLAlchemy URL of this service's own database, e.g.
    #: ``postgresql+psycopg://hospital:pw@postgres:5432/hospital``.
    DATABASE_URL: Optional[str] = None
    #: How long a staff sign-in lasts, in seconds (default 12 hours: one shift).
    SESSION_TTL_SECONDS: int = 43200
    #: Failed sign-ins before an account is locked, and for how long.
    LOGIN_LOCKOUT_ATTEMPTS: int = 8
    LOGIN_LOCKOUT_MINUTES: int = 15
    #: Origins of the staff portal (comma-separated).
    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(default=["http://localhost:3000"])
    DEFAULT_TIMEZONE: str = "Africa/Addis_Ababa"

    # --- Events to and from the Endod patient platform (Redis Streams) ---
    #: A plain Redis URL (development, tests), e.g. ``redis://localhost:6379/0``.
    REDIS_URL: Optional[str] = None
    #: Sentinels as ``host:port`` pairs (comma-separated). When set, the
    #: current master is found through them instead of REDIS_URL.
    REDIS_SENTINELS: Annotated[List[str], NoDecode] = Field(default=[])
    REDIS_SENTINEL_MASTER: str = "endod"
    REDIS_PASSWORD: Optional[str] = None
    #: The sentinels' own password, when they have one (often they do not).
    REDIS_SENTINEL_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    #: Replicas that must hold an event before it counts as sent (WAIT).
    #: 0 with a single Redis; 1 with Sentinel and a replica.
    REDIS_MIN_REPLICAS: int = 0

    # --- Video visits (self-hosted Jitsi with token sign-in) ---
    JITSI_DOMAIN: str = "meet.endod-health.com"
    JITSI_APP_ID: str = "endod"
    JITSI_APP_SECRET: Optional[str] = None
    #: The ``sub`` claim the Jitsi server expects (its XMPP domain).
    JITSI_JWT_SUB: str = "meet.jitsi"

    # --- Hospital sign-up ---
    #: Hospitals may sign themselves up through the portal; Endod approves them.
    SIGNUP_ENABLED: bool = True
    #: Key for Endod's platform-admin endpoints (approve / suspend hospitals).
    PLATFORM_ADMIN_KEY: Optional[str] = None
    #: Reverse proxies in front of this service that append to
    #: X-Forwarded-For (Cloudflare, nginx; the portal passes the header on
    #: unchanged, so it is not a hop). The client address is
    #: the entry this many hops from the right; 0 trusts no header at all.
    TRUSTED_PROXY_HOPS: int = 0

    # --- Patient history (docs/history-events.md) ---
    #: Where uploaded record files are kept (a volume shared by the API and worker).
    FILES_DIR: str = "/data/files"
    #: The Endod platform API on the private bus network, for files of records
    #: patients share with this hospital (called with PLATFORM_ADMIN_KEY).
    PLATFORM_API_URL: Optional[str] = None

    # --- Encryption of health data at rest (app/crypto.py) ---
    #: A file holding the 32-byte master key (KEK) that wraps every hospital's
    #: data key, e.g. /run/secrets/master.key (mounted read-only into the API
    #: and worker only; never in the database or the repository). Required
    #: everywhere but development, where a fixed, public development key is
    #: used when it is not set.
    MASTER_KEY_FILE: Optional[str] = None

    # --- Integration API for hospitals' own systems (docs/integrations.md) ---
    #: A file holding the service's signing key for integration access tokens
    #: (a PEM EC P-256 private key: ``openssl ecparam -name prime256v1 -genkey
    #: -noout -out signing.pem``), mounted read-only like the master key.
    #: Without it, outside development and test, the integration API issues no
    #: tokens (it answers 503).
    INTEGRATIONS_SIGNING_KEY_FILE: Optional[str] = None
    #: The integration API's public base URL (nginx maps it to /integrations/v1
    #: of this service). The token URL, which client assertions must name as
    #: their audience, is this plus ``/oauth/token``.
    INTEGRATIONS_PUBLIC_URL: str = "https://api.endod-health.com/hospital/v1"
    #: The secret nginx sends as ``X-Endod-Edge-Key`` to the integrations
    #: service (app/integrations_main.py), which refuses any request without
    #: it, and answers 503 in production while it is not set.
    EDGE_SHARED_SECRET: Optional[str] = None

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _lower(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("CORS_ORIGINS", "REDIS_SENTINELS", mode="before")
    @classmethod
    def _split(cls, value):
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


def get_settings() -> Settings:
    """Fresh each call: cheap, and tests can change the environment."""
    return Settings()
