"""What a connection may do: technical scope names (the API) and plain words (the portal)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

LABS = "records.labs.write"
PRESCRIPTIONS = "records.prescriptions.write"
DIAGNOSES = "records.diagnoses.write"
VISITS = "records.visits.write"
DOCUMENTS = "records.documents.write"
IMAGING = "records.imaging.write"
PATIENTS_READ = "patients.read"
PATIENTS_WRITE = "patients.write"
BOOKINGS_READ = "bookings.read"
BOOKINGS_WRITE = "bookings.write"
FOLLOWUPS = "followups.write"
PRESCRIPTIONS_READ = "prescriptions.read"
QUEUE = "queue.write"
WEBHOOKS = "webhooks"

#: scope -> (label in the portal, longer description). In the portal's order.
SCOPES: Dict[str, Tuple[str, str]] = {
    LABS: ("Send lab results", "Lab results (FHIR Observation and lab DiagnosticReport); read them back."),
    PRESCRIPTIONS: ("Send prescriptions", "Prescriptions (FHIR MedicationRequest); read them back."),
    DIAGNOSES: ("Send diagnoses", "Diagnoses (FHIR Condition); read them back."),
    VISITS: ("Send visit notes", "Visit notes (FHIR Encounter); read them back."),
    DOCUMENTS: ("Send documents", "PDF and image documents (FHIR DocumentReference); read them back."),
    IMAGING: ("Send imaging reports", "Imaging reports (FHIR DiagnosticReport, imaging); read them back."),
    PATIENTS_READ: ("See patients", "Read a registered patient by hospital number, with their Endod link status."),
    PATIENTS_WRITE: ("Register and link patients", "Register patients (Endod gives the hospital number), link "
                                                   "them to their Endod account, or unlink them."),
    BOOKINGS_READ: ("See bookings", "Read the bookings patients made through Endod."),
    BOOKINGS_WRITE: ("Decide on bookings", "Approve or decline video visits, cancel bookings and mark visits "
                                           "completed, as the portal does."),
    FOLLOWUPS: ("Set follow-ups", "Set, list and cancel follow-up dates (the patient gets an SMS and a reminder)."),
    PRESCRIPTIONS_READ: ("See what pharmacies gave", "Read a prescription with what pharmacies dispensed from it, "
                                                     "item by item."),
    QUEUE: ("Run the queue", "Check patients in to a doctor's queue, call the next one, and mark them done, "
                             "skipped or cancelled."),
    WEBHOOKS: ("Get notified of changes", "Receive events: bookings made, confirmed or cancelled; patients "
                                          "linked, refused or unlinked; prescriptions dispensed."),
}
ALL: Tuple[str, ...] = tuple(SCOPES)
#: The scopes that send FHIR records.
RECORDS: Tuple[str, ...] = (LABS, PRESCRIPTIONS, DIAGNOSES, VISITS, DOCUMENTS, IMAGING)


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
