"use client";

import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { AppointmentRow } from "@/components/appointments/appointment-row";
import type { AppointmentRow as AppointmentRowType } from "@/lib/appointment-types";

const COLUMNS = [
  { label: "Patient Profile & ID", px: "px-space-lg" },
  { label: "Scheduled Time & Type", px: "px-space-md" },
  { label: "Attending Doctor", px: "px-space-md" },
  { label: "Visit Status", px: "px-space-md" },
  { label: "Priority / Notes", px: "px-space-md" },
  { label: "Actions", px: "px-space-lg", alignRight: true },
];

export function AppointmentsTable({
  rows,
  total,
}: {
  rows: AppointmentRowType[];
  total: number;
}) {
  return (
    <div className="mb-space-lg flex flex-col overflow-hidden rounded-2xl bg-surface-container-lowest shadow-soft">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-container-low uppercase tracking-wider text-outline font-label-sm text-label-sm">
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  className={`${column.px} py-3.5 font-medium ${
                    column.alignRight ? "text-right" : ""
                  }`}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-variant font-body-md text-body-md">
            {rows.length > 0 ? (
              rows.map((row) => (
                <AppointmentRow key={row.id} row={row} />
              ))
            ) : (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-space-lg py-10 text-center text-body-sm font-body-sm text-on-surface-variant"
                >
                  No appointments match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-space-sm bg-surface-container-low px-space-lg py-space-md">
        <div className="flex items-center gap-2 text-outline font-body-sm text-body-sm">
          <span>
            Showing <strong className="text-on-surface font-semibold">1-6</strong>
            of{" "}
            <strong className="text-on-surface font-semibold">{total}</strong>
            appointments
          </span>
          <span>•</span>
          <div className="flex items-center gap-1">
            <span>Rows:</span>
            <select
              defaultValue="15"
              className="bg-surface-container-low text-on-surface font-label-sm text-label-sm rounded-lg px-2 py-0.5 focus:outline-none cursor-pointer"
            >
              <option>15</option>
              <option>25</option>
              <option>50</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <PaginationButton disabled icon="chevron_left" />
          {[1, 2, 3].map((page) => (
            <PageButton key={page} page={page} active />
          ))}
          <span className="w-6 text-center text-outline text-xs">...</span>
          <PageButton page={10} />
          <PaginationButton icon="chevron_right" />
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
        "w-8 h-8 rounded-lg flex items-center justify-center font-label-sm text-label-sm font-semibold transition-colors",
        active
          ? "bg-primary-container text-on-primary shadow-xs"
          : "text-on-surface hover:bg-surface-container-high"
      )}
    >
      {page}
    </button>
  );
}

function PaginationButton({
  disabled,
  icon,
}: {
  disabled?: boolean;
  icon: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        "w-8 h-8 rounded-lg flex items-center justify-center transition-colors",
        disabled
          ? "text-outline opacity-40"
          : "text-on-surface hover:bg-surface-container-high hover:text-on-surface"
      )}
    >
      <Icon name={icon} className="text-[18px]" />
    </button>
  );
}
