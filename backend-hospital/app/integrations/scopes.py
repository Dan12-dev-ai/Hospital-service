"""What a connection may do: technical scope names (the API) and plain words (the portal)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

LABS = "records.labs.write"
PRESCRIPTIONS = "records.prescriptions.write"
DIAGNOSES = "records.diagnoses.write"
VISITS = "records.visits.write"
DOCUMENTS = "records.documents.write"
IMAGING = "records.imaging.write"
BOOKINGS_READ = "bookings.read"
WEBHOOKS = "webhooks"

#: scope -> (label in the portal, longer description). In the portal's order.
SCOPES: Dict[str, Tuple[str, str]] = {
    LABS: ("Send lab results", "Lab results (FHIR Observation and lab DiagnosticReport)."),
    PRESCRIPTIONS: ("Send prescriptions", "Prescriptions (FHIR MedicationRequest)."),
    DIAGNOSES: ("Send diagnoses", "Diagnoses (FHIR Condition)."),
    VISITS: ("Send visit notes", "Visit notes (FHIR Encounter)."),
    DOCUMENTS: ("Send documents", "PDF and image documents (FHIR DocumentReference)."),
    IMAGING: ("Send imaging reports", "Imaging reports (FHIR DiagnosticReport, imaging)."),
    BOOKINGS_READ: ("See bookings", "Read the bookings patients made through Endod."),
    WEBHOOKS: ("Get notified of bookings", "Receive events: bookings made, confirmed or cancelled, "
                                          "patients linked or unlinked."),
}
ALL: Tuple[str, ...] = tuple(SCOPES)


def parse(value: Optional[str]) -> List[str]:
    """Space-separated scopes, in order, without repeats (unknown ones kept: the caller checks)."""
    return list(dict.fromkeys((value or "").split()))


def unknown(scopes: List[str]) -> List[str]:
    return [s for s in scopes if s not in SCOPES]


def ordered(scopes) -> List[str]:
    """Known scopes in the portal's order."""
    wanted = set(scopes)
    return [s for s in ALL if s in wanted]


def describe() -> List[Dict[str, str]]:
    return [{"scope": name, "label": label, "description": description}
            for name, (label, description) in SCOPES.items()]
