"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { liveIntake } from "@/lib/dashboard-data";

export function AlertBanner() {
  const { highlightAppointment } = useDashboard();
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div className="flex w-full items-center justify-between gap-4 rounded-2xl bg-pine-green px-5 py-3 text-white shadow-md transition-all duration-300">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-white/20">
          <Icon name="emergency" className="text-[18px] text-emerald-200" />
        </div>
        <div className="truncate text-xs">
          <span className="font-bold text-emerald-200">
            New Booking Intake:
          </span>
          <span className="ml-1 font-semibold text-white">
            {liveIntake.patientName}
          </span>
          <span className="mx-1 rounded bg-black/20 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
            {liveIntake.mrn}
          </span>
          <span className="hidden text-emerald-100 sm:inline">
            • {liveIntake.detail}
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => highlightAppointment(liveIntake.mrn)}
          className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-pine-green shadow-sm transition-colors hover:bg-emerald-50"
        >
          View Details
        </button>
        <button
          type="button"
          aria-label="Dismiss alert"
          onClick={() => setDismissed(true)}
          className="text-emerald-200 transition-colors hover:text-white"
        >
          <Icon name="close" className="text-[18px]" />
        </button>
      </div>
    </div>
  );
}
