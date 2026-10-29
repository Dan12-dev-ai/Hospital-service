import type { Role } from "@/lib/api-types";

export type NavItem = {
  label: string;
  icon: string;
  href: string;
  /** Small pill badge shown on the right of the nav row */
  badge?: string;
  /** Green "online" dot indicator */
  dot?: boolean;
  /** Roles that see this link (everyone when absent). */
  roles?: Role[];
  /** Only for hospitals approved by Endod (not pending or suspended). */
  approvedOnly?: boolean;
};

export type AppointmentStatus = "requested" | "checkedin" | "confirmed";

export type Appointment = {
  id: string;
  patientName: string;
  patientNameAm: string;
  mrn: string;
  doctor: string;
  meta: string;
  time: string;
  status: AppointmentStatus;
  avatar: string;
  /** Message shown in the toast when the row action is clicked */
  actionMessage: string;
};

export type KpiMetric = {
  label: string;
  icon: string;
  value: string;
  /** Only on sample cards (no real trend data exists yet). */
  trend?: string;
  caption: string;
  /** Illustrative numbers, not from the hospital service. */
  sample?: boolean;
};

export type AgendaEvent = {
  id: string;
  title: string;
  time: string;
  description: string;
  /** Timeline dot color class */
  dotClass: string;
  attendees: string[];
};

export type AlertItem = {
  id: string;
  message: string;
};

export type StatusFilter = "all" | AppointmentStatus;
