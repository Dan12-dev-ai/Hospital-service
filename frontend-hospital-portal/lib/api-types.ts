/** Shapes returned by the hospital service (backend-hospital/app/api). */

export type Role =
  | "admin"
  | "doctor"
  | "nurse"
  | "reception"
  | "pharmacist"
  | "billing"
  | "records";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  doctor: "Doctor",
  nurse: "Nurse",
  reception: "Reception",
  pharmacist: "Pharmacist",
  billing: "Billing",
  records: "Records",
};

export type Staff = {
  id: string;
  email: string;
  full_name: string;
  full_name_am: string | null;
  role: Role;
  department_id: string | null;
  phone: string | null;
  active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  hospital?: { id: string; code: string; name: string; name_am: string | null };
};

export type HospitalStatus = "pending" | "approved" | "suspended";
export type HospitalKind = "public" | "private";

export const SERVICES = [
  { key: "general_medicine", label: "General medicine" },
  { key: "emergency", label: "Emergency" },
  { key: "maternal_health", label: "Maternal health" },
  { key: "pediatrics", label: "Pediatrics" },
  { key: "cardiology", label: "Cardiology" },
  { key: "respiratory", label: "Respiratory" },
] as const;

export type ServiceKey = (typeof SERVICES)[number]["key"];

export type Hospital = {
  id: string;
  code: string;
  name: string;
  name_am: string | null;
  timezone: string;
  directory_facility_id: string | null;
  status: HospitalStatus;
  listed: boolean;
  missing_for_listing: string[];
  kind: HospitalKind;
  city: string | null;
  address: string | null;
  phone: string | null;
  ambulance_phone: string | null;
  emergency: boolean;
  latitude: number | null;
  longitude: number | null;
  services: ServiceKey[];
  open_hours: string | null;
  video_enabled: boolean;
  /** Birr, as text with two decimals. */
  price_in_person: string | null;
  price_video: string | null;
  /** People ahead in a queue when the "get ready" SMS goes out (0 = off). */
  queue_notify_ahead: number;
};

export const MISSING_LABELS: Record<string, string> = {
  price_in_person: "an in-person visit price",
  location: "the hospital's location (latitude and longitude)",
};

export type BookingStatus = "awaiting_doctor" | "confirmed" | "rejected" | "cancelled" | "completed";
export type VisitMode = "in_person" | "video";

export type Booking = {
  id: string;
  external_id: string;
  patient: { dedan_id: string; name: string; phone: string | null };
  visit_mode: VisitMode;
  service: string | null;
  scheduled_at: string;
  duration_minutes: number;
  notes: string | null;
  /** Birr, as text with two decimals. */
  price: string;
  status: BookingStatus;
  doctor: { id: string; full_name: string } | null;
  has_video_room: boolean;
  reason: string | null;
  decided_at: string | null;
  created_at: string;
};

export type BookingList = { items: Booking[]; counts: Record<BookingStatus, number> };

export type VideoJoin = { domain: string; room: string; jwt: string; url: string };

export type DutyStatus = "on-duty" | "in-consultation" | "on-call" | "off-duty";
export type DoctorRank = "chief" | "senior-consultant" | "attending" | "resident";

export type ApiDoctor = {
  id: string;
  full_name: string;
  full_name_am: string | null;
  email: string;
  phone: string | null;
  active: boolean;
  department: { id: string; name: string; name_am: string | null } | null;
  license_number: string | null;
  credentials: string | null;
  specialty: string | null;
  rank: DoctorRank | null;
  extension: string | null;
  duty_status: DutyStatus;
  duty_location: string | null;
  duty_updated_at: string | null;
  load: { patients: number; capacity: number | null; percent: number | null };
};

export type DoctorList = {
  items: ApiDoctor[];
  counts: { all: number } & Record<DutyStatus, number>;
};

export type Department = {
  id: string;
  kind: "department" | "ward" | "clinic" | "dispensary";
  name: string;
  name_am: string | null;
  capacity: number | null;
  active: boolean;
};

export type PatientStatus = "opd" | "emergency" | "admitted" | "discharge" | "discharged";

export type ApiPatient = {
  id: string;
  mrn: string;
  dedan_id: string | null;
  full_name: string;
  full_name_am: string | null;
  sex: "female" | "male";
  age_years: number | null;
  status: PatientStatus;
  department: { id: string; name: string; name_am: string | null } | null;
  ward: { id: string; name: string; name_am: string | null } | null;
  bed: string | null;
  attending_doctor: { id: string; full_name: string } | null;
  diagnosis: string | null;
  alerts: { id: string; kind: "allergy" | "risk"; label: string }[];
  status_changed_at: string | null;
};

export type PatientList = { items: ApiPatient[]; total: number; limit: number; offset: number };

export type PatientStats = {
  total: number;
  registered_today: number;
  by_status: Record<PatientStatus, number>;
};
