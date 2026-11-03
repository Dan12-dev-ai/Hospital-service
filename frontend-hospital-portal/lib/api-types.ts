/** Shapes returned by the hospital service (backend-hospital/app/api). */

export type Role =
  | "admin"
  | "developer"
  | "doctor"
  | "nurse"
  | "reception"
  | "pharmacist"
  | "billing"
  | "records";

/** The roles that sign in to the developer dashboard (the backend refuses the others). */
export type DashboardRole = "admin" | "developer";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  developer: "Developer",
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
  /** An authenticator app is set up (two-step verification). */
  two_factor_enrolled?: boolean;
  /** /auth/me only: "full", or a sign-in half-way ("totp": a code is next; "enroll": set up the authenticator). */
  stage?: "full" | "totp" | "enroll";
  recovery_codes_left?: number;
  hospital?: { id: string; code: string; name: string; name_am: string | null; status: HospitalStatus;
    /** The onboarding application is not approved: only it (or its status) is open. */
    locked: boolean;
  };
};

export type HospitalStatus = "pending" | "approved" | "suspended";
export type HospitalKind = "public" | "private";
export type FacilityType = "hospital" | "clinic";

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
  facility_type: FacilityType;
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
  /** Whether Endod offers video visits at all (off by default: no video settings anywhere). */
  video_visits_offered?: boolean;
  /** Birr, as text with two decimals. */
  price_in_person: string | null;
  price_video: string | null;
  /** People ahead in a queue when the "get ready" SMS goes out (0 = off). */
  queue_notify_ahead: number;
};

export const MISSING_LABELS: Record<string, string> = {
  price_in_person: "the in-person visit price",
  location: "the hospital's location on the map",
};

/** One priced item the hospital's system synced (PUT /prices/... in the integration API). */
export type PriceItem = { code: string; name: string; price: string; active: boolean; updated_at: string | null };

export type PriceList = {
  currency: string;
  consultation: { in_person: string | null };
  lab_tests: PriceItem[];
  imaging: PriceItem[];
  procedures: PriceItem[];
};

/** The integration guide, served by the hospital service (GET /developer/guide). */
export type GuideSource = { markdown: string; api_url: string; docs_url: string; openapi_url: string };
