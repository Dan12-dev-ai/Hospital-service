"""Connections (integration clients): ids, secrets, address limits.

* The client_id is public (``endod_live_...`` / ``endod_test_...``).
* The client secret is 48 random URL-safe characters (288 bits) after a
  prefix, shown once. Only its HMAC-SHA256 under a server key (derived from
  the master key) is kept: a secret this random cannot be guessed, so a
  memory-hard hash would only make every token request expensive (and the
  endpoint easy to overload). A leaked table without the master key reveals
  nothing. Unknown clients are checked against a dummy value, so a wrong
  client_id costs the same as a wrong secret. Malformed ids and secrets are
  refused before any database work (:func:`well_formed_client_id`).
* The webhook signing secret is kept encrypted at rest (it must be read to
  sign), and shown once.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from typing import Iterable, List, Optional, Union
from urllib.parse import urlsplit

from app import crypto
from app.models import IntegrationMode

SECRET_PREFIX = "ehs_"
WEBHOOK_SECRET_PREFIX = "whsec_"
MAX_CIDRS = 20

HASH_PREFIX = "hmac-sha256$"
_CLIENT_ID = re.compile(r"^endod_(live|test)_[0-9a-f]{24}$")
_SECRET = re.compile(r"^ehs_[A-Za-z0-9_-]{48}$")
_DUMMY = "ehs_" + "0" * 48


def well_formed_client_id(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(_CLIENT_ID.match(value))


def well_formed_secret(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(_SECRET.match(value))


def _secret_key() -> bytes:
    return hmac.new(crypto.master_key(), b"endod-hospital|integration-client-secrets|v1", hashlib.sha256).digest()


def new_client_id(mode: str) -> str:
    return f"endod_{'test' if mode == IntegrationMode.TEST else 'live'}_{secrets.token_hex(12)}"


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(36)


def new_webhook_secret() -> str:
    return WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return HASH_PREFIX + hmac.new(_secret_key(), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_secret(secret: Optional[str], stored: Optional[str]) -> bool:
    """The same work whether or not the client exists (``stored`` None: a dummy value)."""
    expected = stored if stored and stored.startswith(HASH_PREFIX) else hash_secret(_DUMMY)
    given = hash_secret(secret if isinstance(secret, str) else "")
    return hmac.compare_digest(given, expected) and stored is not None


Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


class CidrError(ValueError):
    pass


def parse_cidrs(values: Iterable[str]) -> List[str]:
    """Addresses or ranges (``196.188.0.0/16``, ``2001:db8::/32``, ``41.79.1.5``), normalised."""
    out: List[str] = []
    for raw in values:
        value = (raw or "").strip()
        if not value:
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise CidrError(f"{value[:60]} is not an IP address or range (e.g. 196.188.10.0/24).") from None
        if network.prefixlen == 0:
            raise CidrError(f"{value[:60]} allows every address; leave the list empty instead.")
        if str(network) not in out:
            out.append(str(network))
    if len(out) > MAX_CIDRS:
        raise CidrError(f"At most {MAX_CIDRS} addresses or ranges.")
    return out


def stored_cidrs(text: Optional[str]) -> List[str]:
    return [part for part in (text or "").split(",") if part]


def address_allowed(address: str, cidrs: List[str]) -> bool:
    """Whether ``address`` is in the allow-list (an empty list allows any address)."""
    if not cidrs:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    for cidr in cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


class WebhookUrlError(ValueError):
    pass


def check_webhook_url(url: str) -> str:
    """An https URL with a host name or a public address (DNS is checked again at every send)."""
    url = (url or "").strip()
    if not url:
        raise WebhookUrlError("Give the address of your system.")
    if len(url) > 500:
        raise WebhookUrlError("The address is too long (500 characters at most).")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise WebhookUrlError("This is not a valid web address.") from None
    if parts.scheme != "https":
        raise WebhookUrlError("The address must start with https:// (encrypted connections only).")
    if not parts.hostname or parts.username or parts.password or "@" in parts.netloc:
        raise WebhookUrlError("The address must name a host, without a user name or password.")
    if parts.fragment:
        raise WebhookUrlError("The address must not have a #fragment.")
    if port is not None and not 0 < port < 65536:
        raise WebhookUrlError("The port is not valid.")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise WebhookUrlError("The address must be reachable on the internet (not a local or internal name).")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise WebhookUrlError("The address must be reachable on the internet (a full host name).") from None
        return url
    from app.integrations.webhooks import public_address

    if not public_address(ip):
        raise WebhookUrlError("The address must be reachable on the internet (not a private or local address).")
    return url
