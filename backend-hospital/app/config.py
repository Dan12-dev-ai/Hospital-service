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
    #: X-Forwarded-For (the portal's server, nginx...). The client address is
    #: the entry this many hops from the right; 0 trusts no header at all.
    TRUSTED_PROXY_HOPS: int = 0

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
