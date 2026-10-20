"use client";

import { DoctorRow } from "@/components/doctors/doctor-row";
import { EmptyState } from "@/components/common/states";
import type { Doctor } from "@/lib/doctor-types";

const COLUMNS = [
  { label: "Doctor Profile & License", align: "left", px: "px-5" },
  { label: "Department & Specialty", align: "left", px: "px-4" },
  { label: "Duty Status", align: "left", px: "px-4" },
  { label: "Today's Patient Load", align: "left", px: "px-4" },
  { label: "Contact & Extension", align: "left", px: "px-4" },
  { label: "Actions", align: "right", px: "px-5" },
];

export function DoctorsTable({
  doctors,
  filtered,
  canAdd,
  canSetDuty,
  canEditProfile,
  onSetDuty,
  onEditProfile,
}: {
  doctors: Doctor[];
  filtered: boolean;
  canAdd: boolean;
  canSetDuty: (doctor: Doctor) => boolean;
  canEditProfile: boolean;
  onSetDuty: (doctor: Doctor) => void;
  onEditProfile: (doctor: Doctor) => void;
}) {
  return (
    <section className="flex flex-col overflow-hidden rounded-2xl bg-surface-container-lowest shadow-sm">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-container-low text-label-sm font-label-sm uppercase tracking-wider text-outline">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`py-3.5 font-semibold ${column.px} ${column.align === "right" ? "text-right" : "text-left"}`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-body-md font-body-md text-on-surface">
            {doctors.length > 0 ? (
              doctors.map((doctor) => (
                <DoctorRow
                  key={doctor.id}
                  doctor={doctor}
                  canSetDuty={canSetDuty(doctor)}
                  canEditProfile={canEditProfile}
                  onSetDuty={() => onSetDuty(doctor)}
                  onEditProfile={() => onEditProfile(doctor)}
                />
              ))
            ) : (
              <tr>
                <td colSpan={COLUMNS.length}>
                  {filtered ? (
                    <EmptyState icon="filter_alt_off" title="No doctors match the current filters." />
                  ) : (
                    <EmptyState icon="stethoscope" title="No doctors yet">
                      {canAdd
                        ? "Add your hospital's doctors with “Add Doctor”. Each gets a one-time password to sign in."
                        : "An administrator adds the hospital's doctors."}
                    </EmptyState>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="bg-surface-container-low px-5 py-4 text-label-sm font-label-sm text-outline">
        <span className="font-medium text-on-surface">Showing {doctors.length} doctors</span>
      </div>
    </section>
  );
}
