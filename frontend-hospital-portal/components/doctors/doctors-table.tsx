"use client";

import { Icon } from "@/components/ui/icon";
import { DoctorRow } from "@/components/doctors/doctor-row";
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
  total,
}: {
  doctors: Doctor[];
  total: number;
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
                  className={`py-3.5 font-semibold ${column.px} ${
                    column.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-body-md font-body-md text-on-surface">
            {doctors.length > 0 ? (
              doctors.map((doctor) => (
                <DoctorRow key={doctor.id} doctor={doctor} />
              ))
            ) : (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-5 py-10 text-center text-body-sm font-body-sm text-on-surface-variant"
                >
                  No doctors match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex flex-col items-center justify-between gap-3 bg-surface-container-low px-5 py-4 text-label-sm font-label-sm text-outline sm:flex-row">
        <div className="flex items-center gap-2">
          <span className="font-medium text-on-surface">
            Showing 1-{doctors.length} of {total} doctors
          </span>
          <span>•</span>
          <div className="flex items-center gap-1.5">
            <span>Rows:</span>
            <select
              aria-label="Rows per page"
              defaultValue="15"
              className="rounded-lg border-none bg-surface-container-lowest px-2 py-0.5 text-label-sm font-label-sm text-on-surface focus:ring-1 focus:ring-primary-container"
            >
              <option>15</option>
              <option>25</option>
              <option>50</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled
            aria-label="Previous page"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-surface-container hover:text-on-surface disabled:opacity-40"
          >
            <Icon name="chevron_left" className="text-[18px]" />
          </button>
          {[1, 2, 3].map((page) => (
            <PageButton key={page} page={page} active={page === 1} />
          ))}
          <span className="px-1 text-outline">…</span>
          <PageButton page={10} />
          <button
            type="button"
            aria-label="Next page"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            <Icon name="chevron_right" className="text-[18px]" />
          </button>
        </div>
      </div>
    </section>
  );
}

function PageButton({ page, active }: { page: number; active?: boolean }) {
  return (
    <button
      type="button"
      className={`flex h-8 w-8 items-center justify-center rounded-lg text-label-sm font-label-sm transition-colors ${
        active
          ? "bg-primary-container font-semibold text-on-primary shadow-sm"
          : "text-on-surface-variant hover:bg-surface-container"
      }`}
    >
      {page}
    </button>
  );
}
