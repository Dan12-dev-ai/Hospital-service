"""Input types shared by the API routers."""

from __future__ import annotations

import re
from typing import Annotated, Any, Optional

from pydantic import AfterValidator, BeforeValidator, StringConstraints


def blank_to_none(value: Any) -> Any:
    """Forms send "" for an empty optional field; store it as no value."""
    if isinstance(value, str):
        return value.strip() or None
    return value


#: A required name: surrounding spaces dropped, then at least two characters.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2)]
#: An optional text field where "" means none.
OptionalText = Annotated[Optional[str], BeforeValidator(blank_to_none)]

_DIGITS = re.compile(r"\D")


def normalize_phone(value: str) -> str:
    """An Ethiopian mobile number as +2519XXXXXXXX / +2517XXXXXXXX.

    Accepts the ways it is usually written: 0911 234 567, 911234567,
    +251 911 234 567, 251911234567.
    """
    digits = _DIGITS.sub("", value)
    if digits.startswith("251"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 9 or digits[0] not in "79":
        raise ValueError("enter an Ethiopian mobile number, e.g. 0911 234 567")
    return "+251" + digits


def _optional_phone(value: Optional[str]) -> Optional[str]:
    return normalize_phone(value) if value else None


#: An optional Ethiopian mobile number, stored as +251XXXXXXXXX.
OptionalPhone = Annotated[Optional[str], BeforeValidator(blank_to_none), AfterValidator(_optional_phone)]


_PHONE_LIKE = re.compile(r"^[\d\s+()-]+$")


_CONTACT = re.compile(r"^\+?[\d\s()-]{3,20}$")


def _contact_number(value: Optional[str]) -> Optional[str]:
    """A hospital's phone or hotline: a mobile (stored +251...), a landline or a short code like 907."""
    if value is None:
        return None
    if not _CONTACT.match(value):
        raise ValueError("enter a phone number, e.g. 011 551 7611, 0911 234 567 or 907")
    try:
        return normalize_phone(value)
    except ValueError:
        return re.sub(r"\s+", " ", value).strip()


#: A hospital phone number or hotline (mobile, landline or short code).
ContactNumber = Annotated[Optional[str], BeforeValidator(blank_to_none), AfterValidator(_contact_number)]


def phone_digits(query: str) -> Optional[str]:
    """The national digits of a phone number typed into a search box, if it looks like one.

    "0911", "0911 234 567" and "+251 911..." all qualify; "SPH-000124" does not.
    """
    if not _PHONE_LIKE.match(query.strip()):
        return None
    digits = _DIGITS.sub("", query)
    if len(digits) < 4:
        return None
    if digits.startswith("251"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    return digits[:9] or None


def like_pattern(term: str) -> str:
    """``%term%`` for a LIKE escaped with a backslash, so % and _ typed by a user match literally."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_ENDOD_ID = re.compile(r"^DE-?(\d{6})$")


def normalize_dedan_id(value: str) -> str:
    """An Endod ID as the platform writes it: DE and six digits (DE482731).

    Also accepts the forms staff type or older records carry: de482731, DE-482731.
    """
    match = _ENDOD_ID.match(re.sub(r"\s+", "", value or "").upper())
    if not match:
        raise ValueError("not a valid Endod ID, e.g. DE482731")
    return "DE" + match.group(1)


_STORED_ENDOD_ID = re.compile(r"^DE\d{6}$")


def is_dedan_id(value: Any) -> bool:
    """True for an Endod ID exactly as stored and sent: DE and six digits."""
    return isinstance(value, str) and bool(_STORED_ENDOD_ID.match(value))


def checked_dedan_id(value: Optional[str]) -> Optional[str]:
    """None, or an Endod ID as stored (DE482731); anything else raises ValueError.

    Every column that holds a confirmed Endod ID goes through this (see
    app.models), so a free-typed value is never stored, or sent to Endod.
    """
    if value is not None and not is_dedan_id(value):
        raise ValueError(f"not an Endod ID in stored form (DE + 6 digits): {value!r}")
    return value


def _dedan(value: Optional[str]) -> Optional[str]:
    return normalize_dedan_id(value) if value else None


#: An optional Endod ID, stored as DE + 6 digits.
OptionalDedanId = Annotated[Optional[str], BeforeValidator(blank_to_none), AfterValidator(_dedan)]
