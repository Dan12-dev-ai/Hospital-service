"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { AppointmentRow } from "@/components/dashboard/appointment-row";
import { appointments } from "@/lib/appointments-data";
import type { StatusFilter } from "@/lib/dashboard-types";

const FILTERS: { key: StatusFilter; label: (count: number) => string }[] = [
  { key: "all", label: (count) => `All (${count})` },
  { key: "requested", label: (count) => `Requested (${count})` },
  { key: "checkedin", label: (count) => `Checked In (${count})` },
  { key: "confirmed", label: (count) => `Confirmed (${count})` },
];

export function AppointmentsCard() {
  const { searchQuery } = useDashboard();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const counts = useMemo(
    () => ({
      all: appointments.length,
      requested: appointments.filter((a) => a.status === "requested").length,
      checkedin: appointments.filter((a) => a.status === "checkedin").length,
      confirmed: appointments.filter((a) => a.status === "confirmed").length,
    }),
    []
  );

  const filtered = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return appointments.filter((appointment) => {
      const matchesStatus =
        statusFilter === "all" || appointment.status === statusFilter;
      const matchesSearch =
        !query ||
        appointment.patientName.toLowerCase().includes(query) ||
        appointment.patientNameAm.includes(query) ||
        appointment.mrn.toLowerCase().includes(query) ||
        appointment.doctor.toLowerCase().includes(query);
      return matchesStatus && matchesSearch;
    });
  }, [searchQuery, statusFilter]);

  return (
    <div className="flex flex-col rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex flex-col justify-between gap-2 border-b border-slate-100 pb-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-sm font-bold text-slate-800">
            Today&apos;s Appointments
          </h2>
          <span className="text-[11px] text-slate-400">
            Upcoming and ongoing appointments
          </span>
        </div>
        {/* Quick status tab filters */}
        <div className="custom-scrollbar flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={() => setStatusFilter(filter.key)}
              className={cn(
                "whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] transition-colors",
                statusFilter === filter.key
                  ? "bg-pine-green font-semibold text-white"
                  : "font-medium text-slate-600 hover:bg-slate-100"
              )}
            >
              {filter.label(counts[filter.key])}
            </button>
          ))}
        </div>
      </div>

      {/* Appointments List Items */}
      <div className="mt-2 divide-y divide-slate-100">
        {filtered.length > 0 ? (
          filtered.map((appointment) => (
            <AppointmentRow
              key={appointment.id}
              appointment={appointment}
            />
          ))
        ) : (
          <p className="px-2 py-6 text-center text-xs text-slate-400">
            No appointments match your search
            {searchQuery ? ` for “${searchQuery}”` : ""}.
          </p>
        )}
      </div>
    </div>
  );
}
