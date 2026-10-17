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
