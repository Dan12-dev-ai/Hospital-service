"""Input types shared by the API routers."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Optional

from pydantic import AfterValidator, BeforeValidator, Field, StringConstraints


def blank_to_none(value: Any) -> Any:
    """Forms send "" for an empty optional field; store it as no value."""
    if isinstance(value, str):
        return value.strip() or None
    return value


#: A required name: surrounding spaces dropped, then at least two characters.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2)]
#: An optional text field where "" means none.
OptionalText = Annotated[Optional[str], BeforeValidator(blank_to_none)]

#: A visit price in birr, up to two decimals, 0 (free) to 1,000,000. Stored in
#: santim (an integer): see santim() and birr().
Birr = Annotated[Decimal, Field(ge=0, le=1_000_000, decimal_places=2)]


def santim(value: Decimal) -> int:
    """A price in birr as the integer santim it is stored as."""
    return int((value * 100).to_integral_value())


def birr(value: Optional[int]) -> Optional[str]:
    """Stored santim as birr, text with two decimals (exact; never a float)."""
    return None if value is None else f"{Decimal(value) / 100:.2f}"


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


# --- opening hours --------------------------------------------------------------------------------

#: Day names as stored (and shown to patients in the Endod app).
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
#: Always open.
ALWAYS_OPEN = "24/7"
_ALWAYS_OPEN_SPELLINGS = {"24/7", "24 hours", "24h", "24hrs", "24 hrs", "open 24 hours", "24 hours, 7 days"}
_DAY_NAMES = {name.lower(): name for name in DAYS}
_DAY_NAMES.update({full: short for full, short in (
    ("monday", "Mon"), ("tuesday", "Tue"), ("wednesday", "Wed"), ("thursday", "Thu"), ("friday", "Fri"),
    ("saturday", "Sat"), ("sunday", "Sun"), ("tues", "Tue"), ("thur", "Thu"), ("thurs", "Thu"))})
_DASHES = re.compile(r"\s*[-–—]\s*")
_PERIOD = re.compile(r"^(?P<days>[A-Za-z]+(?:-[A-Za-z]+)?)\s+(?P<open>\d{1,2}[:.]\d{2})-(?P<close>\d{1,2}[:.]\d{2})$")
OPEN_HOURS_HELP = 'use "24/7", or days and times like "Mon-Fri 08:00-17:00, Sat 08:00-12:00"'


def _clock(value: str) -> str:
    hours, minutes = (int(part) for part in re.split(r"[:.]", value))
    if not (0 <= hours <= 24 and 0 <= minutes <= 59) or (hours == 24 and minutes):
        raise ValueError(f"{value} is not a time of day; {OPEN_HOURS_HELP}")
    return f"{hours:02d}:{minutes:02d}"


def _day(value: str) -> str:
    day = _DAY_NAMES.get(value.lower())
    if day is None:
        raise ValueError(f'"{value}" is not a day (use Mon, Tue, Wed, Thu, Fri, Sat, Sun); {OPEN_HOURS_HELP}')
    return day


def normalize_open_hours(value: str) -> str:
    """Opening hours as patients see them: "24/7", or periods such as
    "Mon-Fri 08:00-17:00, Sat 08:00-12:00" ("Daily 08:00-20:00" for every day).

    Accepts the usual spellings (8:00, 8.00, en dashes, full day names, ";"
    between periods) and stores the form above; anything else (e.g. "100:00")
    raises ValueError with a message staff can act on.
    """
    text = re.sub(r"\s+", " ", value).strip()
    if text.lower() in _ALWAYS_OPEN_SPELLINGS:
        return ALWAYS_OPEN
    periods = []
    for part in re.split(r"\s*[,;]\s*", text):
        match = _PERIOD.match(_DASHES.sub("-", part))
        if not match:
            raise ValueError(f'"{part}" is not a period of opening hours; {OPEN_HOURS_HELP}')
        days = match.group("days")
        if days.lower() in ("daily", "everyday"):
            label = "Daily"
        else:
            first, _, last = days.partition("-")
            label = _day(first)
            if last:
                if DAYS.index(_day(last)) < DAYS.index(label):
                    raise ValueError(f'{part}: the days must run forward, e.g. "Mon-Fri" (write "Sat-Sun, Mon-Tue" '
                                     f'for a weekend into the week); {OPEN_HOURS_HELP}')
                label += f"-{_day(last)}"
        opens, closes = _clock(match.group("open")), _clock(match.group("close"))
        if opens == closes or opens == "24:00":
            raise ValueError(f"{part}: the closing time must differ from the opening time; {OPEN_HOURS_HELP}")
        periods.append(f"{label} {opens}-{closes}")
    result = ", ".join(periods)
    if len(result) > 80:
        raise ValueError("opening hours are too long (80 characters at most); combine days, e.g. Mon-Fri")
    return result


def _open_hours(value: Optional[str]) -> Optional[str]:
    return normalize_open_hours(value) if value else None


#: Optional opening hours ("" means none), stored as normalize_open_hours writes them.
OptionalOpenHours = Annotated[Optional[str], BeforeValidator(blank_to_none), AfterValidator(_open_hours)]
#: Required opening hours.
OpenHours = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
                      AfterValidator(normalize_open_hours)]
