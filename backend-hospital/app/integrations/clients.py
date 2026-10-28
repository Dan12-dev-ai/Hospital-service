"""Connections (integration clients): ids, secrets, address limits.

* The client_id is public (``endod_live_...`` / ``endod_test_...``).
* The client secret is 48 random URL-safe characters after a prefix, shown
  once; only its argon2id hash is kept. Unknown clients are checked against a
  dummy hash, so a wrong client_id costs the same as a wrong secret.
* The webhook signing secret is kept encrypted at rest (it must be read to
  sign), and shown once.
"""

from __future__ import annotations

import ipaddress
import secrets
from typing import Iterable, List, Optional, Union
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.models import IntegrationMode

SECRET_PREFIX = "ehs_"
WEBHOOK_SECRET_PREFIX = "whsec_"
MAX_CIDRS = 20

# argon2id, OWASP's minimum (19 MiB, 2 passes): the secret is random and long,
# the hash only has to make a stolen table useless.
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(36))


def new_client_id(mode: str) -> str:
    return f"endod_{'test' if mode == IntegrationMode.TEST else 'live'}_{secrets.token_hex(12)}"


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(36)


def new_webhook_secret() -> str:
    return WEBHOOK_SECRET_PREFIX + secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_secret(secret: Optional[str], stored: Optional[str]) -> bool:
    """Constant work whether or not the client exists (``stored`` None: the dummy hash)."""
    try:
        return _hasher.verify(stored or _DUMMY_HASH, secret or "") and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


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
