"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

export function AutoDispatchStrip() {
  const { showToast } = useDashboard();

  return (
    <section className="flex flex-col items-center justify-between gap-3 rounded-2xl bg-surface-container-lowest p-4 shadow-sm md:flex-row">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-container-high text-primary">
          <Icon name="schedule_send" className="text-[20px]" />
        </div>
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="font-label-lg text-label-md text-on-surface">
              Scheduled Auto-Dispatches
            </span>
            <span className="h-2 w-2 rounded-full bg-secondary" />
          </div>
          <span className="font-body-sm text-body-sm text-outline">
            6 statutory reports queued for MoH weekly submission at 18:00 EAT
            (ቅዱስ ጳውሎስ ሚሌኒየም)
          </span>
        </div>
      </div>
      <div className="flex w-full items-center justify-end gap-3 md:w-auto">
        <button
          type="button"
          onClick={() => showToast("Opening auto-dispatch schedule configurator")}
          className="flex items-center gap-1 font-label-md text-label-sm text-primary transition-all hover:underline"
        >
          <span>Configure Schedule</span>
          <Icon name="arrow_forward" className="text-[16px]" />
        </button>
        <button
          type="button"
          onClick={() => showToast("Viewing dispatch logs for scheduled reports")}
          className="rounded-xl bg-surface-container-low px-3 py-1.5 font-label-md text-label-sm text-on-surface transition-colors hover:bg-surface-container"
        >
          View Dispatch Logs
        </button>
      </div>
    </section>
  );
}
