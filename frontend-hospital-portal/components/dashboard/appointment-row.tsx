"use client";

import { useEffect, useRef } from "react";
import Image from "next/image";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import type { Appointment } from "@/lib/dashboard-types";

const STATUS_STYLES: Record<
  Appointment["status"],
  { label: string; badgeClass: string }
> = {
  requested: {
    label: "Requested",
    badgeClass: "border-rose-100 bg-rose-50 font-bold text-rose-600",
  },
  checkedin: {
    label: "Waiting",
    badgeClass: "border-amber-100 bg-amber-50 font-semibold text-amber-700",
  },
  confirmed: {
    label: "Confirmed",
    badgeClass:
      "border-neutral-100 bg-neutral-50 font-semibold text-black",
  },
};

function RowAction({ appointment }: { appointment: Appointment }) {
  const { showToast } = useDashboard();

  switch (appointment.status) {
    case "requested":
      return (
        <button
          type="button"
          onClick={() => showToast(appointment.actionMessage)}
          className="h-8 rounded-full bg-black px-3 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#1f2937]"
        >
          Review &amp; Confirm
        </button>
      );
    case "checkedin":
      return (
        <button
          type="button"
          onClick={() => showToast(appointment.actionMessage)}
          className="flex h-8 items-center gap-1 rounded-full bg-neutral-600 px-3 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-neutral-700"
        >
          <Icon name="play_arrow" className="text-[14px]" />
          Start Visit
        </button>
      );
    case "confirmed":
      return (
        <button
          type="button"
          onClick={() => showToast(appointment.actionMessage)}
          className="h-8 rounded-full bg-slate-100 px-3 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-200"
        >
          Check In
        </button>
      );
  }
}

export function AppointmentRow({ appointment }: { appointment: Appointment }) {
  const { highlightedMrn } = useDashboard();
  const rowRef = useRef<HTMLDivElement>(null);
  const isHighlighted = highlightedMrn === appointment.mrn;

  useEffect(() => {
    if (isHighlighted) {
      rowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isHighlighted]);

  const status = STATUS_STYLES[appointment.status];

  return (
    <div
      ref={rowRef}
      className={`flex flex-col justify-between gap-3 rounded-2xl px-2 py-3 transition-all sm:flex-row sm:items-center ${
        isHighlighted ? "bg-neutral-100/70" : "hover:bg-slate-50/70"
      }`}
    >
      <div className="flex items-center gap-3">
        <Image
          src={appointment.avatar}
          alt={appointment.patientName}
          width={40}
          height={40}
          className="h-10 w-10 rounded-full border border-slate-200 object-cover"
        />
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-slate-800">
              {appointment.patientName}
            </span>
            <span className="rounded bg-slate-100 px-1.5 py-px font-mono text-[10px] text-slate-600">
              {appointment.mrn}
            </span>
            <span className="text-[11px] text-slate-400">
              {appointment.patientNameAm}
            </span>
          </div>
          <span className="text-[11px] text-slate-500">
            {appointment.doctor} • {appointment.meta}
          </span>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <Icon name="schedule" className="text-[15px] text-slate-400" />
          <span className="text-[11px] font-medium">{appointment.time}</span>
        </div>
        <span
          className={`rounded-full border px-2.5 py-1 text-[11px] ${status.badgeClass}`}
        >
          {status.label}
        </span>
        <RowAction appointment={appointment} />
      </div>
    </div>
  );
}
