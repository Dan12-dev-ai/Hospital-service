import type { ApiDoctor, DoctorRank, DutyStatus } from "@/lib/api-types";

export type DoctorStatus = DutyStatus;
export type DoctorStatusFilter = "all" | DoctorStatus;

export const DUTY_LABELS: Record<DutyStatus, string> = {
  "on-duty": "On Duty",
  "in-consultation": "In Consultation",
  "on-call": "On-Call / Surgery",
  "off-duty": "Off Duty",
};

export const RANK_OPTIONS: { value: DoctorRank; label: string }[] = [
  { value: "chief", label: "Chief of Department" },
  { value: "senior-consultant", label: "Senior Consultant" },
  { value: "attending", label: "Attending Physician" },
  { value: "resident", label: "Resident / Fellow" },
];

const STATUS_STYLES: Record<DutyStatus, { badge: string; dot: string; bar: string }> = {
  "on-duty": { badge: "bg-neutral-200 text-neutral-800 font-medium", dot: "bg-neutral-600", bar: "bg-black" },
  "in-consultation": { badge: "bg-neutral-200 text-neutral-800 font-medium", dot: "bg-black animate-pulse", bar: "bg-black" },
  "on-call": { badge: "bg-tertiary-fixed/30 text-tertiary-container font-medium", dot: "bg-tertiary", bar: "bg-tertiary" },
  "off-duty": { badge: "bg-surface-container text-on-surface-variant", dot: "bg-outline", bar: "bg-outline" },
};

/** What a row of the doctors table shows, derived from the API's doctor. */
export type Doctor = {
  id: string;
  name: string;
  nameAm: string | null;
  license: string;
  credentials: string | null;
  departmentLabel: string;
  specialty: string | null;
  rankLabel: string | null;
  status: DoctorStatus;
  statusLabel: string;
  statusBadgeClass: string;
  statusDotClass: string;
  loadLabel: string;
  loadCaption: string;
  loadPercent: number;
  loadBarClass: string;
  phone: string;
  extension: string;
  source: ApiDoctor;
};

export function toDoctorView(doctor: ApiDoctor): Doctor {
  const style = STATUS_STYLES[doctor.duty_status];
  const { patients, capacity, percent } = doctor.load;
  return {
    id: doctor.id,
    name: doctor.full_name,
    nameAm: doctor.full_name_am,
    license: doctor.license_number ?? "No licence on file",
    credentials: doctor.credentials,
    departmentLabel: doctor.department?.name ?? "No department",
    specialty: doctor.specialty,
    rankLabel: RANK_OPTIONS.find((r) => r.value === doctor.rank)?.label ?? null,
    status: doctor.duty_status,
    statusLabel: doctor.duty_location
      ? `${DUTY_LABELS[doctor.duty_status]} • ${doctor.duty_location}`
      : DUTY_LABELS[doctor.duty_status],
    statusBadgeClass: style.badge,
    statusDotClass: style.dot,
    loadLabel: capacity ? `${patients} / ${capacity} Patients` : `${patients} Patients`,
    loadCaption: percent !== null ? `${percent}%` : "No capacity set",
    loadPercent: percent ?? 0,
    loadBarClass: style.bar,
    phone: doctor.phone ?? "—",
    extension: doctor.extension ? `Ext. ${doctor.extension}` : "",
    source: doctor,
  };
}
