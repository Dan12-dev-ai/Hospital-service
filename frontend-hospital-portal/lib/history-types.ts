/** Patient history as the hospital service returns it (backend-hospital/app/api/history.py and friends). */

import type { Role } from "@/lib/api-types";

export type LinkRequestStatus = "pending" | "linked" | "refused" | "superseded";

export type LinkState = {
  patient_id: string;
  dedan_id: string | null;
  /** An Endod ID the patient gave, not confirmed (cleared once linked). */
  claimed_dedan_id: string | null;
  request: {
    id: string;
    dedan_id: string;
    method: "card" | "phone";
    status: LinkRequestStatus;
    reason: string | null;
    linked_name: string | null;
    created_at: string | null;
    decided_at: string | null;
  } | null;
};

export type RecordCategory = "diagnosis" | "prescription" | "lab_result" | "imaging" | "visit_note" | "document";

export const CATEGORY_LABELS: Record<RecordCategory, string> = {
  diagnosis: "Diagnosis",
  prescription: "Prescription",
  lab_result: "Lab result",
  imaging: "Imaging",
  visit_note: "Visit note",
  document: "Document",
};

export const CATEGORY_ICONS: Record<RecordCategory, string> = {
  diagnosis: "diagnosis",
  prescription: "medication",
  lab_result: "biotech",
  imaging: "radiology",
  visit_note: "clinical_notes",
  document: "description",
};

export type RecordFile = { id: string; filename: string; content_type: string; size: number; sha256: string };

export type ClinicalRecord = {
  id: string;
  patient_id: string;
  visit_id: string | null;
  category: RecordCategory;
  title: string;
  details: Record<string, unknown>;
  occurred_at: string;
  recorded_by: string | null;
  source: "portal" | "import";
  version: number;
  retracted: boolean;
  retracted_reason: string | null;
  retracted_at: string | null;
  /** Endod has this version. */
  published: boolean;
  published_version: number | null;
  files: RecordFile[];
  /** Prescriptions only (null otherwise): what pharmacies gave through Endod (docs/pharmacy.md). */
  dispensing?: Dispensing | null;
};

export type DispenseItem = {
  item_index: number;
  /** Given at this dispense (null: not counted). */
  amount: number | null;
  complete: boolean;
  /** Given so far, at every pharmacy (null: not counted). */
  given_total: number | null;
  status: "not_given" | "partly_given" | "given";
  /** From the prescription as it is now. */
  drug: string | null;
  quantity_total: number | null;
};

export type Dispense = {
  dispense_id: string;
  at: string;
  /** As the pharmacist typed it (not verified). */
  pharmacy_name: string;
  status: "open" | "completed";
  items: DispenseItem[];
};

export type Dispensing = { status: "not_dispensed" | "partly" | "fully"; dispenses: Dispense[] };

export type RecordList = { items: ClinicalRecord[]; linked: boolean };

export type Visit = {
  id: string;
  patient_id: string;
  booking_id: string | null;
  started_at: string;
  doctor: { id: string; full_name: string | null } | null;
  follow_up_on: string | null;
  follow_up_note: string | null;
  follow_up_sent: boolean;
};

export type QueueStatus = "waiting" | "called" | "done" | "skipped" | "cancelled";

export type QueueEntry = {
  id: string;
  ticket: number;
  status: QueueStatus;
  ahead: number;
  patient_name: string;
  phone: string | null;
  dedan_id: string | null;
  patient_id: string | null;
  booking_id: string | null;
  checked_in_at: string;
  called_at: string | null;
  finished_at: string | null;
};

export type DoctorQueue = {
  doctor: { id: string; full_name: string };
  entries: QueueEntry[];
  /** The previous day's entries still open: called first, cancelled 12 hours after that day ended. */
  leftovers: (QueueEntry & { day: string })[];
  waiting: number;
  called: QueueEntry | null;
};

export type QueueBoard = { day: string; today: string; notify_ahead: number; queues: DoctorQueue[] };

export type SharedFile = { file_id: string; filename: string; content_type: string; size: number; sha256: string };

export type SharedRecord = {
  id: string;
  record_id: string;
  origin: string;
  category: RecordCategory;
  title: string;
  details: Record<string, unknown>;
  occurred_at: string;
  recorded_by: string | null;
  files: SharedFile[];
};

export type Share = {
  share_id: string;
  dedan_id: string | null;
  patient_name: string | null;
  expires_at: string | null;
  received_at: string;
  records: SharedRecord[];
  patient: { id: string; mrn: string; full_name: string } | null;
};

export type ImportItem = {
  index: number;
  what: string;
  patient: string;
  category: RecordCategory;
  title: string;
  occurred_at: string;
  recorded_by: string | null;
  file: { filename: string; content_type: string; size: number } | null;
};

export type ImportPreview = {
  import_id: string;
  format: "fhir" | "csv";
  filename: string | null;
  items: ImportItem[];
  skipped: { index: number; what: string; reason: string }[];
};

/** The backend's role rules (backend-hospital/app/api/history.py, queue.py, imports.py). */
export const LINKERS: Role[] = ["admin", "reception", "records"];
export const RECORD_READERS: Role[] = ["admin", "doctor", "nurse", "pharmacist", "records"];
export const RECORD_WRITERS: Role[] = ["doctor", "nurse"];
export const DOCUMENT_FILERS: Role[] = ["admin", "records"];
export const DOCUMENT_CATEGORIES: RecordCategory[] = ["document", "lab_result"];
export const FOLLOW_UP_SETTERS: Role[] = ["doctor"];
export const QUEUE_DESK: Role[] = ["admin", "reception"];
export const IMPORTERS: Role[] = ["admin", "records"];

export function categoriesFor(role: Role): RecordCategory[] {
  if (RECORD_WRITERS.includes(role)) return Object.keys(CATEGORY_LABELS) as RecordCategory[];
  if (DOCUMENT_FILERS.includes(role)) return DOCUMENT_CATEGORIES;
  return [];
}

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_FILES_PER_RECORD = 10;
export const ACCEPTED_FILES = "application/pdf,image/jpeg,image/png,image/webp,.pdf,.jpg,.jpeg,.png,.webp";

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
