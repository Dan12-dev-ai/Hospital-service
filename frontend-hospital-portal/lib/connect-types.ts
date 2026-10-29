/** "Connect your system": the hospital's own systems connected to the integration API (backend app/api/connections.py). */

export type ConnectionMode = "live" | "test";

export type Connection = {
  id: string;
  name: string;
  client_id: string;
  mode: ConnectionMode;
  scopes: string[];
  /** The scopes in plain words, e.g. "Send lab results". */
  abilities: string[];
  auth_method: "client_secret" | "private_key_jwt";
  allowed_ips: string[];
  webhook_url: string | null;
  public_keys: number;
  created_at: string;
  created_by: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type ScopeInfo = { scope: string; label: string; description: string };

/** Where the integration API is (the same in every answer). */
export type ApiInfo = {
  api_url: string;
  token_url: string;
  docs_url: string;
  jwks_url: string;
  fhir_url: string;
  mrn_system: string;
  scopes: ScopeInfo[];
};

export type ConnectionList = ApiInfo & { items: Connection[] };

export type NewConnectionResult = ApiInfo & {
  connection: Connection;
  client_secret: string;
  webhook_secret: string | null;
};

export type RequestLogEntry = {
  at: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  ip: string | null;
};

export type Delivery = {
  id: string;
  event_id: string;
  event_type: string;
  status: "pending" | "delivered" | "failed";
  attempts: number;
  last_status_code: number | null;
  last_error: string | null;
  created_at: string;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  delivered_at: string | null;
};

/** The scope that asks for an address to send notifications to. */
export const NOTIFY_SCOPE = "webhooks";

/** The checkboxes of step 2, in order, in plain words (the backend's labels win when they differ). */
export const ABILITIES: { scope: string; label: string; hint: string }[] = [
  { scope: "records.labs.write", label: "Send lab results", hint: "Lab tests and panels" },
  { scope: "records.prescriptions.write", label: "Send prescriptions", hint: "Medicines prescribed" },
  { scope: "records.diagnoses.write", label: "Send diagnoses", hint: "Conditions diagnosed" },
  { scope: "records.visits.write", label: "Send visit notes", hint: "Why the patient came, what was found" },
  { scope: "records.documents.write", label: "Send documents", hint: "PDFs and images" },
  { scope: "records.imaging.write", label: "Send imaging reports", hint: "X-ray, CT, ultrasound reports" },
  { scope: "bookings.read", label: "See bookings", hint: "Bookings patients made through Endod" },
  { scope: NOTIFY_SCOPE, label: "Get notified of bookings", hint: "Your system is told when bookings change" },
];

/** "a few seconds ago", "5 minutes ago", "3 days ago". */
export function timeAgo(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "just now";
  const units: [number, string][] = [
    [60, "minute"],
    [3600, "hour"],
    [86400, "day"],
    [2592000, "month"],
  ];
  let label = "minute";
  let size = 60;
  for (const [s, name] of units) {
    if (seconds >= s) {
      size = s;
      label = name;
    }
  }
  const count = Math.max(1, Math.round(seconds / size));
  return `${count} ${label}${count === 1 ? "" : "s"} ago`;
}
