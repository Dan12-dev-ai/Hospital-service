import type { ApiPatient, PatientStatus, Role } from "@/lib/api-types";

export type PatientStatusKey = PatientStatus;
export type PatientTabKey = "all" | PatientStatusKey;

/** The backend's rules (backend-hospital/app/api/patients.py). */
export const PATIENT_REGISTRARS: Role[] = ["admin", "reception", "records", "nurse", "doctor"];
export const CLINICAL_EDITORS: Role[] = ["admin", "doctor", "nurse"];

export const PATIENT_TABS: { key: PatientTabKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "admitted", label: "In-Patient" },
  { key: "opd", label: "Outpatient" },
  { key: "emergency", label: "Emergency" },
  { key: "discharge", label: "Discharge Pending" },
  { key: "discharged", label: "Discharged" },
];

export const STATUS_LABELS: Record<PatientStatus, string> = {
  opd: "Outpatient",
  emergency: "Emergency",
  admitted: "Admitted",
  discharge: "Discharge Pending",
  discharged: "Discharged",
};

const STATUS_STYLES: Record<PatientStatus, { badge: string; dot: string }> = {
  admitted: { badge: "bg-primary-fixed/30 text-primary", dot: "bg-primary" },
  opd: { badge: "bg-secondary-fixed/30 text-secondary", dot: "bg-secondary" },
  emergency: { badge: "bg-error-container/60 text-error", dot: "bg-error animate-pulse" },
  discharge: { badge: "bg-tertiary-fixed/30 text-tertiary", dot: "bg-tertiary" },
  discharged: { badge: "bg-surface-container text-on-surface-variant", dot: "bg-outline" },
};

export type PatientFlag = { icon: string; label: string; className: string };

/** What a row of the patients table shows, derived from the API's patient. */
export type Patient = {
  id: string;
  mrn: string;
  dedanId: string | null;
  name: string;
  nameAm: string | null;
  demographics: string;
  status: PatientStatusKey;
  statusLabel: string;
  statusBadgeClass: string;
  statusDotClass: string;
  location: string;
  doctor: string;
  doctorDepartment: string;
  diagnosis: string | null;
  flags: PatientFlag[];
};

export function toPatientView(p: ApiPatient): Patient {
  const style = STATUS_STYLES[p.status];
  const place = p.ward ? [p.ward.name, p.bed].filter(Boolean).join(" • ") : p.department?.name ?? "";
  return {
    id: p.id,
    mrn: p.mrn,
    dedanId: p.dedan_id,
    name: p.full_name,
    nameAm: p.full_name_am,
    demographics: `${p.age_years ?? "?"}y ${p.sex === "female" ? "F" : "M"}`,
    status: p.status,
    statusLabel: STATUS_LABELS[p.status],
    statusBadgeClass: style.badge,
    statusDotClass: style.dot,
    location: place,
    doctor: p.attending_doctor?.full_name ?? "Not assigned",
    doctorDepartment: p.department?.name ?? "",
    diagnosis: p.diagnosis,
    flags: p.alerts.map((alert) => ({
      icon: alert.kind === "allergy" ? "warning" : "priority_high",
      label: alert.label,
      className: alert.kind === "allergy" ? "bg-error-container/60 text-error" : "bg-tertiary-fixed/30 text-tertiary",
    })),
  };
}
