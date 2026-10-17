"use client";

import Image from "next/image";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { totalRegisteredPatients } from "@/lib/patients-data";
import type { Patient } from "@/lib/patient-types";

const COLUMNS = [
  { label: "Patient Profile & ID", align: "left" },
  { label: "Clinical Status", align: "left" },
  { label: "Attending MD", align: "left" },
  { label: "Diagnosis / Risk Flags", align: "left" },
  { label: "Actions", align: "right" },
];

export function PatientsTable({
  patients,
  dense,
}: {
  patients: Patient[];
  dense: boolean;
}) {
  const padding = dense ? "py-2" : "py-3.5";

  return (
    <div className="flex min-w-0 flex-col rounded-3xl bg-surface-container-lowest p-5 shadow-soft">
      <div className="custom-scrollbar -mx-2 overflow-x-auto">
        <table className="w-full min-w-[700px] border-collapse text-left">
          <thead>
            <tr className="font-label-sm text-label-sm text-outline">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`px-3 py-3 font-semibold uppercase tracking-wider ${
                    column.align === "right" ? "text-right" : ""
                  }`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-container-low font-body-md text-body-md text-on-surface">
            {patients.length > 0 ? (
              patients.map((patient) => (
                <PatientRow key={patient.id} patient={patient} padding={padding} />
              ))
            ) : (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-10 text-center text-body-sm font-body-sm text-on-surface-variant"
                >
                  No patients match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex flex-col justify-between gap-3 border-t border-surface-container-low pt-5 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <span className="text-body-sm font-body-sm text-outline">
            Showing 1-{patients.length} of {totalRegisteredPatients} patients
          </span>
          <div className="flex items-center gap-1">
            <span className="text-label-sm font-label-sm text-outline">
              Rows:
            </span>
            <select
              aria-label="Rows per page"
              defaultValue="15"
              className="cursor-pointer rounded-lg bg-surface-container-low px-2 py-1 text-label-sm font-label-sm text-on-surface focus:outline-none"
            >
              <option>15</option>
              <option>25</option>
              <option>50</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1 self-end sm:self-auto">
          <button
            type="button"
            disabled
            aria-label="Previous page"
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container disabled:opacity-40"
          >
            <Icon name="chevron_left" className="text-[16px]" />
          </button>
          <PageButton page={1} active />
          <PageButton page={2} />
          <PageButton page={3} />
          <span className="px-1 font-label-sm text-label-sm text-outline">
            ...
          </span>
          <PageButton page={415} />
          <button
            type="button"
            aria-label="Next page"
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container"
          >
            <Icon name="chevron_right" className="text-[16px]" />
          </button>
        </div>
      </div>
    </div>
  );
}

function PageButton({ page, active }: { page: number; active?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-xl font-label-sm text-label-sm transition-colors",
        active
          ? "bg-primary text-on-primary"
          : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container"
      )}
    >
      {page}
    </button>
  );
}

function PatientRow({
  patient,
  padding,
}: {
  patient: Patient;
  padding: string;
}) {
  const { showToast } = useDashboard();

  return (
    <tr className="transition-colors hover:bg-surface-container-low/50">
      {/* Patient Profile & ID */}
      <td className={`px-3 ${padding}`}>
        <div className="flex items-center gap-3">
          <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-2xl bg-surface-container">
            <Image
              src={patient.photo}
              alt={`Portrait of ${patient.name}`}
              width={40}
              height={40}
              className="h-full w-full object-cover"
            />
          </div>
          <div className="flex min-w-0 flex-col">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-label-lg font-label-lg text-on-surface">
                {patient.name}
              </span>
              <span className="text-body-sm font-body-sm text-outline">
                ({patient.nameAm})
              </span>
            </div>
            <span className="flex items-center gap-1.5 text-body-sm font-body-sm text-on-surface-variant">
              <span className="font-medium text-primary">{patient.id}</span>
              <span>•</span>
              <span>{patient.sph}</span>
              <span>•</span>
              <span>{patient.demographics}</span>
            </span>
          </div>
        </div>
      </td>

      {/* Clinical Status */}
      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col items-start gap-1">
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-label-sm font-label-sm ${patient.statusBadgeClass}`}
          >
            <span
              className={`mr-1.5 h-1.5 w-1.5 rounded-full ${patient.statusDotClass}`}
            />
            {patient.statusLabel}
          </span>
          <span className="text-body-sm font-body-sm text-outline">
            {patient.location}
          </span>
        </div>
      </td>

      {/* Attending MD */}
      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col">
          <span className="text-label-md font-label-md text-on-surface">
            {patient.doctor}
          </span>
          <span className="text-body-sm font-body-sm text-outline">
            {patient.doctorDepartment}
          </span>
        </div>
      </td>

      {/* Diagnosis / Risk Flags */}
      <td className={`px-3 ${padding}`}>
        <div className="flex flex-col items-start gap-1">
          <span className="text-body-sm font-body-sm text-on-surface">
            {patient.diagnosis}
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-label-sm font-label-sm ${patient.flag.className}`}
          >
            <Icon name={patient.flag.icon} className="text-[12px]" />
            {patient.flag.label}
          </span>
        </div>
      </td>

      {/* Actions */}
      <td className={`px-3 ${padding} text-right`}>
        <div className="flex items-center justify-end gap-1 text-on-surface-variant">
          <button
            type="button"
            title="Patient EHR Chart"
            aria-label={`Open EHR chart for ${patient.name}`}
            onClick={() => showToast(patient.chartMessage)}
            className="rounded-xl p-1.5 transition-colors hover:bg-surface-container hover:text-primary"
          >
            <Icon name="assignment" className="text-[18px]" />
          </button>
          <button
            type="button"
            title="Schedule Follow-up"
            aria-label={`Schedule follow-up for ${patient.name}`}
            onClick={() => showToast(patient.scheduleMessage)}
            className="rounded-xl p-1.5 transition-colors hover:bg-surface-container hover:text-primary"
          >
            <Icon name="calendar_today" className="text-[18px]" />
          </button>
          <button
            type="button"
            title="Options"
            aria-label={`More options for ${patient.name}`}
            onClick={() => showToast("More clinical options")}
            className="rounded-xl p-1.5 transition-colors hover:bg-surface-container"
          >
            <Icon name="more_vert" className="text-[18px]" />
          </button>
        </div>
      </td>
    </tr>
  );
}
