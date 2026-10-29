"""The service's key that signs integration access tokens (ES256).

A PEM EC P-256 private key in the file named by
``HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE`` (mounted read-only into the API
and worker, like the master key; never in the database or the repository).
Its public half is published at ``/.well-known/jwks.json`` with its ``kid``
(the RFC 7638 thumbprint), which every token names.

Without the file, an environment set explicitly to development or test signs
with a key made at start (tokens die with the process); anywhere else the
integration API issues no tokens and answers 503 (it fails closed).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings
from app.crypto import KEYLESS_ENVIRONMENTS
from app.integrations import jose

logger = logging.getLogger("hospital.integrations")


class SigningKeyMissing(RuntimeError):
    """No usable signing key: the integration API is not available."""


@dataclass(frozen=True)
class SigningKey:
    private: ec.EllipticCurvePrivateKey
    public: jose.PublicKey
    kid: str

    def __repr__(self) -> str:  # never the key itself
        return f"SigningKey(kid={self.kid!r})"


_lock = threading.Lock()
_cache: Dict[str, SigningKey] = {}


def _make(private: ec.EllipticCurvePrivateKey) -> SigningKey:
    jwk = jose.ec_public_jwk(private.public_key())
    kid = jose.thumbprint(jwk)
    return SigningKey(private, jose.public_key({**jwk, "kid": kid, "alg": jose.ES256, "use": "sig"}), kid)


def _load(path: str) -> SigningKey:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SigningKeyMissing(f"The integrations signing key file {path} cannot be read ({exc.strerror}).") from None
    try:
        private = serialization.load_pem_private_key(raw, password=None)
    except (ValueError, TypeError):
        raise SigningKeyMissing("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE must hold a PEM EC P-256 private key "
                                "(openssl ecparam -name prime256v1 -genkey -noout -out signing.pem).") from None
    if not isinstance(private, ec.EllipticCurvePrivateKey) or private.curve.name != "secp256r1":
        raise SigningKeyMissing("The integrations signing key must be an EC P-256 key (ES256).")
    return _make(private)


def _keyless_allowed(settings) -> bool:
    return settings.ENVIRONMENT in KEYLESS_ENVIRONMENTS and "ENVIRONMENT" in settings.model_fields_set


def signing_key() -> SigningKey:
    """The signing key (read once per file path). Raises SigningKeyMissing."""
    settings = get_settings()
    path = settings.INTEGRATIONS_SIGNING_KEY_FILE
    with _lock:
        if path:
            key = _cache.get(path)
            if key is None:
                key = _cache[path] = _load(path)
                logger.info("integrations_signing_key_loaded kid=%s", key.kid)
            return key
        if _keyless_allowed(settings):
            key = _cache.get("")
            if key is None:
                key = _cache[""] = _make(ec.generate_private_key(ec.SECP256R1()))
                logger.warning("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE is not set: integration tokens are signed "
                               "with a key made at start (HOSPITAL_ENVIRONMENT=%s only)", settings.ENVIRONMENT)
            return key
    raise SigningKeyMissing("HOSPITAL_INTEGRATIONS_SIGNING_KEY_FILE is not set: the integration API is off.")


def check_at_start() -> Optional[str]:
    """Logs whether the integration API can issue tokens; returns the kid (None: it cannot)."""
    try:
        return signing_key().kid
    except SigningKeyMissing as exc:
        logger.warning("integrations_disabled %s", exc)
        return None


def jwks() -> Dict[str, Any]:
    key = signing_key()
    return {"keys": [{**key.public.jwk, "kid": key.kid, "alg": jose.ES256, "use": "sig"}]}


def clear_cache() -> None:
    with _lock:
        _cache.clear()
