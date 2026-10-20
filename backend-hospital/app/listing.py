"""What the Endod patient app knows about each hospital.

An approved hospital is announced to the patient platform with a full
snapshot (``hospital.listed``) whenever anything patients see changes; a
suspended one is withdrawn (``hospital.unlisted``). The platform keeps its
own copy, so patients can browse hospitals even when this service is down.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app import eventbus
from app.models import Hospital, HospitalStatus, Service


def services_of(hospital: Hospital) -> List[str]:
    return [s for s in (hospital.services or "").split(",") if s in Service.ALL]


def snapshot(hospital: Hospital) -> Dict[str, Any]:
    """Everything the patient app shows about the hospital (no staff or patient data)."""
    return {
        "hospital_id": hospital.id,
        "code": hospital.code,
        "name": hospital.name,
        "name_am": hospital.name_am,
        "kind": hospital.kind,
        "city": hospital.city,
        "address": hospital.address,
        "phone": hospital.phone,
        "ambulance_phone": hospital.ambulance_phone,
        "emergency": hospital.emergency,
        "latitude": hospital.latitude,
        "longitude": hospital.longitude,
        "services": services_of(hospital),
        "open_hours": hospital.open_hours,
        "timezone": hospital.timezone,
        "video_enabled": bool(hospital.video_enabled and hospital.price_video is not None),
        "price_in_person": hospital.price_in_person,
        "price_video": hospital.price_video,
    }


def bookable(hospital: Hospital) -> bool:
    """Approved, and with what a patient needs to book: a price and a place."""
    return (hospital.status == HospitalStatus.APPROVED and hospital.price_in_person is not None
            and hospital.latitude is not None and hospital.longitude is not None)


def announce(session: Session, hospital: Hospital) -> None:
    """Tell the patient platform the hospital's current listing (in this transaction)."""
    if bookable(hospital):
        eventbus.emit(session, "hospital.listed", snapshot(hospital))
    else:
        eventbus.emit(session, "hospital.unlisted", {"hospital_id": hospital.id})


def missing_for_listing(hospital: Hospital) -> List[str]:
    """What an approved hospital still has to fill in before patients can see it."""
    missing = []
    if hospital.price_in_person is None:
        missing.append("price_in_person")
    if hospital.latitude is None or hospital.longitude is None:
        missing.append("location")
    return missing
