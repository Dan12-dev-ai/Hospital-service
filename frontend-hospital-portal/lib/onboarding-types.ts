/** The onboarding application (backend-hospital/app/onboarding.py). */

import type { FacilityType, HospitalKind, ServiceKey } from "@/lib/api-types";

export type ApplicationStatus = "draft" | "submitted" | "rejected" | "approved";
export type StepKey = "contact" | "facility" | "location" | "documents" | "demo" | "review";
export type DocumentKind = "moh_license" | "trade_license" | "tin_certificate" | "owner_id";

export type ApplicationDocument = {
  kind: DocumentKind;
  label: string;
  uploaded: boolean;
  filename?: string;
  content_type?: string;
  size?: number;
  sha256?: string;
  uploaded_at?: string;
};

export type Application = {
  hospital_id: string;
  code: string;
  status: ApplicationStatus;
  hospital_status: "pending" | "approved" | "suspended";
  next_step: StepKey;
  missing: Record<Exclude<StepKey, "review">, string[]>;
  complete: boolean;
  created_at: string | null;
  submitted_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  contact: { full_name: string | null; title: string | null; phone: string | null; email: string | null };
  facility: {
    facility_type: FacilityType;
    ownership: HospitalKind;
    name: string;
    name_am: string | null;
    city: string | null;
    phone: string | null;
    services: ServiceKey[];
    open_hours: string | null;
  };
  location: { address: string | null; latitude: number | null; longitude: number | null };
  documents: { license_number: string | null; items: ApplicationDocument[] };
  demo: { booking_id: string; demo_at: string; timezone: string; minutes: number } | null;
};

export type DemoSlots = {
  timezone: string;
  minutes: number;
  current: string | null;
  days: { date: string; slots: string[] }[];
};

export const STEPS: { key: StepKey; title: string; short: string }[] = [
  { key: "contact", title: "Your account", short: "Account" },
  { key: "facility", title: "Your facility", short: "Facility" },
  { key: "location", title: "Where to find you", short: "Location" },
  { key: "documents", title: "Documents", short: "Documents" },
  { key: "demo", title: "Book a demo", short: "Demo" },
  { key: "review", title: "Review and submit", short: "Review" },
];

/** Endod runs demos on Addis Ababa time, wherever the viewer is. */
export const DEMO_TIME_ZONE = "Africa/Addis_Ababa";

export function formatDemo(iso: string): string {
  const when = new Date(iso);
  const date = new Intl.DateTimeFormat("en-GB", {
    timeZone: DEMO_TIME_ZONE,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(when);
  return `${date}, ${formatTime(iso)}`;
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: DEMO_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
