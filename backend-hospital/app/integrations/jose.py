"""Compact JWS with ES256 and RS256, and public JWKs (RFC 7515, 7517, 7518, 7638).

Deliberately small: only the two algorithms SMART Backend Services names,
the algorithm must agree with the key's type (no "none", no HMAC, so no
algorithm confusion), and the token's size and JSON are bounded.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

ES256 = "ES256"
RS256 = "RS256"
ALGORITHMS = (ES256, RS256)
#: Longest token read (a client assertion or an access token is far shorter).
MAX_TOKEN = 8 * 1024
#: Keys one client may publish.
MAX_KEYS = 10
MIN_RSA_BITS = 2048
#: JWK members that only a private key has: refused (a client must never paste one).
PRIVATE_MEMBERS = ("d", "p", "q", "dp", "dq", "qi", "oth", "k")


class JoseError(ValueError):
    """A token or key is malformed, or a signature does not verify."""


def b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64decode(text: str) -> bytes:
    if not isinstance(text, str) or any(c not in _B64URL for c in text) or len(text) % 4 == 1:
        raise JoseError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise JoseError("not base64url") from None


_B64URL = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _json(segment: str) -> Dict[str, Any]:
    try:
        value = json.loads(b64decode(segment).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise JoseError("not a JSON object") from None
    if not isinstance(value, dict):
        raise JoseError("not a JSON object")
    return value


@dataclass(frozen=True)
class Parsed:
    header: Dict[str, Any]
    claims: Dict[str, Any]
    signing_input: bytes
    signature: bytes


def parse(token: str) -> Parsed:
    """Split and decode a compact JWS, without checking its signature."""
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
        raise JoseError("the token is missing or too long")
    parts = token.split(".")
    if len(parts) != 3:
        raise JoseError("not a compact JWS")
    header, claims = _json(parts[0]), _json(parts[1])
    if header.get("alg") not in ALGORITHMS:
        raise JoseError("the algorithm must be ES256 or RS256")
    if "crit" in header:
        raise JoseError("critical header parameters are not supported")
    return Parsed(header, claims, f"{parts[0]}.{parts[1]}".encode("ascii"), b64decode(parts[2]))


# --- keys ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class PublicKey:
    alg: str
    kid: Optional[str]
    key: Any  # ec.EllipticCurvePublicKey or rsa.RSAPublicKey
    jwk: Dict[str, Any]


def _int(value: Any, name: str) -> int:
    if not isinstance(value, str):
        raise JoseError(f"the key's {name} is missing")
    return int.from_bytes(b64decode(value), "big")


def public_key(jwk: Any) -> PublicKey:
    """A signing key from a public JWK: EC P-256 (ES256) or RSA of 2048 bits or more (RS256)."""
    if not isinstance(jwk, dict):
        raise JoseError("a key must be a JSON object")
    if any(member in jwk for member in PRIVATE_MEMBERS):
        raise JoseError("this is a PRIVATE key: paste only the public keys (never share the private key)")
    kty, alg, use, kid = jwk.get("kty"), jwk.get("alg"), jwk.get("use"), jwk.get("kid")
    if use is not None and use != "sig":
        raise JoseError("a key's use must be sig")
    if kid is not None and (not isinstance(kid, str) or not 0 < len(kid) <= 200):
        raise JoseError("a key's kid must be a short string")
    if kty == "EC":
        if jwk.get("crv") != "P-256" or alg not in (None, ES256):
            raise JoseError("an EC key must be P-256 (ES256)")
        x, y = b64decode(jwk.get("x") or ""), b64decode(jwk.get("y") or "")
        if len(x) != 32 or len(y) != 32:
            raise JoseError("the EC key's x and y must be 32 bytes")
        try:
            key = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                                ec.SECP256R1()).public_key()
        except ValueError:
            raise JoseError("the EC key is not on the P-256 curve") from None
        clean = {"kty": "EC", "crv": "P-256", "x": jwk["x"], "y": jwk["y"]}
        return PublicKey(ES256, kid, key, {**clean, **({"kid": kid} if kid else {})})
    if kty == "RSA":
        if alg not in (None, RS256):
            raise JoseError("an RSA key must be used with RS256")
        n, e = _int(jwk.get("n"), "n"), _int(jwk.get("e"), "e")
        if n.bit_length() < MIN_RSA_BITS:
            raise JoseError(f"an RSA key must have at least {MIN_RSA_BITS} bits")
        if e < 3 or e % 2 == 0:
            raise JoseError("the RSA key's exponent is not valid")
        try:
            key = rsa.RSAPublicNumbers(e, n).public_key()
        except ValueError:
            raise JoseError("the RSA key is not valid") from None
        clean = {"kty": "RSA", "n": jwk["n"], "e": jwk["e"]}
        return PublicKey(RS256, kid, key, {**clean, **({"kid": kid} if kid else {})})
    raise JoseError("a key's kty must be EC or RSA")


def parse_jwks(value: Any) -> List[PublicKey]:
    """A JWKS (``{"keys": [...]}``, as JSON text or already parsed): public signing keys only."""
    if isinstance(value, str):
        if len(value) > 64 * 1024:
            raise JoseError("the key set is too long")
        try:
            value = json.loads(value)
        except ValueError:
            raise JoseError("the key set is not valid JSON") from None
    if not isinstance(value, dict) or not isinstance(value.get("keys"), list) or not value["keys"]:
        raise JoseError('the key set must be {"keys": [ ... ]} with at least one key')
    if len(value["keys"]) > MAX_KEYS:
        raise JoseError(f"at most {MAX_KEYS} keys")
    keys = [public_key(jwk) for jwk in value["keys"]]
    kids = [k.kid for k in keys if k.kid]
    if len(kids) != len(set(kids)):
        raise JoseError("two keys have the same kid")
    return keys


def jwks_json(keys: List[PublicKey]) -> str:
    """The key set as stored: the public members only, in a canonical form."""
    return json.dumps({"keys": [k.jwk for k in keys]}, sort_keys=True, separators=(",", ":"))


def thumbprint(jwk: Dict[str, Any]) -> str:
    """RFC 7638 JWK thumbprint (SHA-256), base64url."""
    members = ("crv", "kty", "x", "y") if jwk["kty"] == "EC" else ("e", "kty", "n")
    canonical = json.dumps({m: jwk[m] for m in members}, sort_keys=True, separators=(",", ":"))
    return b64encode(hashlib.sha256(canonical.encode("utf-8")).digest())


# --- signatures -------------------------------------------------------------------------------

def verify_signature(parsed: Parsed, key: PublicKey) -> None:
    if parsed.header.get("alg") != key.alg:
        raise JoseError("the token's algorithm does not match the key")
    try:
        if key.alg == ES256:
            if len(parsed.signature) != 64:
                raise JoseError("an ES256 signature is 64 bytes")
            r = int.from_bytes(parsed.signature[:32], "big")
            s = int.from_bytes(parsed.signature[32:], "big")
            key.key.verify(encode_dss_signature(r, s), parsed.signing_input, ec.ECDSA(hashes.SHA256()))
        else:
            key.key.verify(parsed.signature, parsed.signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise JoseError("the signature does not verify") from None


def select_key(parsed: Parsed, keys: List[PublicKey]) -> PublicKey:
    """The key the token names (its kid), or the only key of its algorithm."""
    kid = parsed.header.get("kid")
    candidates = [k for k in keys if k.alg == parsed.header.get("alg")]
    if kid is not None:
        candidates = [k for k in candidates if k.kid == kid]
    if len(candidates) != 1:
        raise JoseError("no single key matches the token's kid and algorithm")
    return candidates[0]


def verify(token: str, keys: List[PublicKey]) -> Parsed:
    parsed = parse(token)
    verify_signature(parsed, select_key(parsed, keys))
    return parsed


def sign_es256(private_key: ec.EllipticCurvePrivateKey, header: Dict[str, Any], claims: Dict[str, Any]) -> str:
    head = b64encode(json.dumps({**header, "alg": ES256}, separators=(",", ":")).encode("utf-8"))
    body = b64encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    der = private_key.sign(f"{head}.{body}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{head}.{body}.{b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def sign_rs256(private_key: rsa.RSAPrivateKey, header: Dict[str, Any], claims: Dict[str, Any]) -> str:
    """For tests and examples (clients sign their assertions with their own keys)."""
    head = b64encode(json.dumps({**header, "alg": RS256}, separators=(",", ":")).encode("utf-8"))
    body = b64encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signature = private_key.sign(f"{head}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64encode(signature)}"


def ec_public_jwk(key: ec.EllipticCurvePublicKey, kid: Optional[str] = None) -> Dict[str, Any]:
    numbers = key.public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": b64encode(numbers.x.to_bytes(32, "big")),
           "y": b64encode(numbers.y.to_bytes(32, "big"))}
    return {**jwk, **({"kid": kid} if kid else {})}


def rsa_public_jwk(key: rsa.RSAPublicKey, kid: Optional[str] = None) -> Dict[str, Any]:
    numbers = key.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "n": b64encode(n), "e": b64encode(e), **({"kid": kid} if kid else {})}

