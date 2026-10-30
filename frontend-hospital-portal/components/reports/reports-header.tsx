"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

export function ReportsHeader() {
  const { showToast } = useDashboard();

  return (
    <header className="flex flex-col justify-between gap-4 rounded-3xl bg-surface-container-lowest p-6 shadow-soft lg:flex-row lg:items-center">
      <div className="flex flex-col gap-1">
        <h1 className="text-headline-lg font-headline-lg font-bold tracking-tight text-on-surface">
          Reports &amp; Analytics
        </h1>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => showToast("Period selector: This Month (Meskerem / Tikimt)")}
          className="flex items-center gap-2 rounded-xl bg-surface-container-lowest px-3.5 py-2.5 text-label-lg font-label-md text-on-surface shadow-sm transition-colors hover:bg-surface-container-low"
        >
          <Icon name="date_range" className="text-[18px] text-outline" />
          <span>This Month (Meskerem / Tikimt)</span>
          <Icon name="expand_more" className="text-[16px] text-outline" />
        </button>
        <button
          type="button"
          onClick={() => showToast("Batch Export queued for all visible reports")}
          className="flex items-center gap-2 rounded-xl bg-surface-container-lowest px-3.5 py-2.5 text-label-lg font-label-md text-on-surface shadow-sm transition-colors hover:bg-surface-container-low"
        >
          <Icon name="ios_share" className="text-[18px] text-outline" />
          <span>Batch Export</span>
        </button>
        <button
          type="button"
          onClick={() => showToast("Opening new report generator (አዲስ ሪፖርት)")}
          className="flex items-center gap-2 rounded-xl bg-black px-4 py-2.5 text-label-lg font-label-md text-white shadow-glow transition-all hover:bg-neutral-800"
        >
          <Icon name="add_circle" className="text-[20px]" />
          <span>Generate Report (አዲስ ሪፖርት)</span>
        </button>
      </div>
    </header>
  );
}
