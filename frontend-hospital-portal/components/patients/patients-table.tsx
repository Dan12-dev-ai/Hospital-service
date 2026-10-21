"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/icon";
import { EmptyState } from "@/components/common/states";
import type { PatientStatus } from "@/lib/api-types";
import { initialsOf } from "@/lib/format";
import { STATUS_LABELS, type Patient } from "@/lib/patient-types";

const COLUMNS = [
  { label: "Patient Profile & ID", align: "left" },
  { label: "Clinical Status", align: "left" },
  { label: "Attending MD", align: "left" },
  { label: "Diagnosis / Risk Flags", align: "left" },
  { label: "Actions", align: "right" },
];

/**
 * Status moves offered from the directory. Admission needs a ward and bed,
 * which belong on the patient's chart, so it is not offered here.
 */
function nextStatuses(current: PatientStatus): PatientStatus[] {
  const options: PatientStatus[] = ["opd", "emergency"];
  if (current === "admitted") options.push("discharge");
  options.push("discharged");
  return options.filter((s) => s !== current);
}

export function PatientsTable({
  patients,
  dense,
  total,
  offset,
  pageSize,
  pageSizes,
  onPageSizeChange,
  onPrevious,
  onNext,
  filtered,
  canRegister,
  canChangeStatus,
  onChangeStatus,
}: {
  patients: Patient[];
  dense: boolean;
  total: number;
  offset: number;
  pageSize: number;
  pageSizes: number[];
  onPageSizeChange: (size: number) => void;
  onPrevious: () => void;
  onNext: () => void;
  filtered: boolean;
  canRegister: boolean;
  canChangeStatus: boolean;
  onChangeStatus: (patientId: string, status: PatientStatus) => void;
}) {
  const padding = dense ? "py-2" : "py-3.5";
  const from = patients.length ? offset + 1 : 0;
  const to = offset + patients.length;

  return (
    <div className="flex min-w-0 flex-col rounded-3xl bg-surface-container-lowest p-5 shadow-soft">
      <div className="custom-scrollbar -mx-2 overflow-x-auto">
        <table className="w-full min-w-[700px] border-collapse text-left">
          <thead>
            <tr className="font-label-sm text-label-sm text-outline">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`px-3 py-3 font-semibold uppercase tracking-wider ${column.align === "right" ? "text-right" : ""}`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-container-low font-body-md text-body-md text-on-surface">
            {patients.length > 0 ? (
              patients.map((patient) => (
                <PatientRow
                  key={patient.id}
                  patient={patient}
                  padding={padding}
                  canChangeStatus={canChangeStatus}
                  onChangeStatus={onChangeStatus}
                />
              ))
            ) : (
              <tr>
                <td colSpan={COLUMNS.length}>
                  {filtered ? (
                    <EmptyState icon="person_search" title="No patients match the current filters." />
                  ) : (
                    <EmptyState icon="person_add" title="No patients registered yet">
                      {canRegister ? "Register the first patient with “Register Patient”." : "Registration staff add patients here."}
                    </EmptyState>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex flex-col justify-between gap-3 border-t border-surface-container-low pt-5 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <span className="text-body-sm font-body-sm text-outline">
            Showing {from}-{to} of {total.toLocaleString("en-US")} patients
          </span>
          <div className="flex items-center gap-1">
            <span className="text-label-sm font-label-sm text-outline">Rows:</span>
            <select
              aria-label="Rows per page"
              value={pageSize}
              onChange={(event) => onPageSizeChange(Number(event.target.value))}
              className="cursor-pointer rounded-lg bg-surface-container-low px-2 py-1 text-label-sm font-label-sm text-on-surface focus:outline-none"
            >
              {pageSizes.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1 self-end sm:self-auto">
          <button
            type="button"
            disabled={offset === 0}
            onClick={onPrevious}
            aria-label="Previous page"
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container disabled:opacity-40"
          >
            <Icon name="chevron_left" className="text-[16px]" />
          </button>
          <span className="px-2 font-label-sm text-label-sm text-on-surface">
            Page {Math.floor(offset / pageSize) + 1} of {Math.max(1, Math.ceil(total / pageSize))}
          </span>
          <button
            type="button"
            disabled={to >= total}
            onClick={onNext}
            aria-label="Next page"
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container disabled:opacity-40"
          >
            <Icon name="chevron_right" className="text-[16px]" />
          </button>
        </div>
      </div>
    </div>
  );
}

function PatientRow({
  patient,
  padding,
  canChangeStatus,
  onChangeStatus,
}: {
  patient: Patient;
  padding: string;
  canChangeStatus: boolean;
  onChangeStatus: (patientId: string, status: PatientStatus) => void;
}) {
  return (
    <tr data-testid="patient-row" className="transition-colors hover:bg-surface-container-low/50">
      <td className={`px-3 ${padding}`}>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-surface-container text-xs font-bold text-primary">
            {initialsOf(patient.name)}
          </div>
          <div className="flex min-w-0 flex-col">
            <div className="flex items-center gap-1.5">
              <Link href={`/patients/${patient.id}`} className="truncate text-label-lg font-label-lg text-on-surface hover:text-primary hover:underline">
                {patient.name}
              </Link>
              {patient.nameAm && <span className="text-body-sm font-body-sm text-outline">({patient.nameAm})</span>}
            </div>
            <span className="flex items-center gap-1.5 text-body-sm font-body-sm text-on-surface-variant">
              <span className="font-medium text-primary">{patient.mrn}</span>
              {patient.dedanId && (
                <>
                  <span>•</span>
                  <span>{patient.dedanId}</span>
                </>
              )}
              <span>•</span>
              <span>{patient.demographics}</span>
            </span>
          </div>
        </div>
      </td>

      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col items-start gap-1">
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-label-sm font-label-sm ${patient.statusBadgeClass}`}>
            <span className={`mr-1.5 h-1.5 w-1.5 rounded-full ${patient.statusDotClass}`} />
            {patient.statusLabel}
          </span>
          {patient.location && <span className="text-body-sm font-body-sm text-outline">{patient.location}</span>}
        </div>
      </td>

      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col">
          <span className="text-label-md font-label-md text-on-surface">{patient.doctor}</span>
          <span className="text-body-sm font-body-sm text-outline">{patient.doctorDepartment}</span>
        </div>
      </td>

      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col items-start gap-1">
          <span className="text-body-sm font-body-sm text-on-surface">{patient.diagnosis ?? "—"}</span>
          {patient.flags.map((flag) => (
            <span key={flag.label} className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-label-sm font-label-sm ${flag.className}`}>
              <Icon name={flag.icon} className="text-[12px]" />
              {flag.label}
            </span>
          ))}
        </div>
      </td>

      <td className={`px-3 ${padding} text-right`}>
        {canChangeStatus ? (
          <select
            aria-label={`Change status of ${patient.name}`}
            value=""
            onChange={(event) => {
              if (event.target.value) onChangeStatus(patient.id, event.target.value as PatientStatus);
            }}
            className="cursor-pointer rounded-xl bg-surface-container-low px-2 py-1.5 text-label-sm font-label-sm text-on-surface focus:outline-none"
          >
            <option value="">Move to…</option>
            {nextStatuses(patient.status).map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-body-sm font-body-sm text-outline">—</span>
        )}
      </td>
    </tr>
  );
}
