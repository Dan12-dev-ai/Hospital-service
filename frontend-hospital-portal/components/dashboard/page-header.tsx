"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { facility } from "@/lib/dashboard-data";

export function PageHeader() {
  const { showToast } = useDashboard();

  return (
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Dashboard
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Welcome back! Here&apos;s what&apos;s happening today at{" "}
          {facility.fullName}.
        </p>
      </div>
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={() => showToast("Opening appointment scheduling modal...")}
          className="flex items-center gap-1.5 rounded-2xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
        >
          <Icon name="calendar_add_on" className="text-[18px]" />
          <span>New Appointment</span>
        </button>
        <button
          type="button"
          onClick={() =>
            showToast("Exporting Clinical Roster for Addis Ababa MOH...")
          }
          className="flex items-center gap-1.5 rounded-2xl bg-pine-green px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#145243]"
        >
          <Icon name="person_add" className="text-[18px]" />
          <span>Register Patient</span>
        </button>
      </div>
    </div>
  );
}
