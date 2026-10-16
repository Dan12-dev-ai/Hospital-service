"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { facility } from "@/lib/dashboard-data";

export function DoctorsHeader({ activeCount }: { activeCount: number }) {
  const { showToast } = useDashboard();

  return (
    <header className="flex flex-col justify-between gap-4 border-b border-surface-container pb-6 md:flex-row md:items-center">
      <div>
        <div className="mb-1 flex items-center gap-2 text-label-sm font-label-sm uppercase tracking-wide text-outline">
          <span>Clinical Staff</span>
          <span>•</span>
          <span className="font-semibold text-primary">
            Staff Directory &amp; Roster
          </span>
        </div>
        <h1 className="flex items-center gap-2 text-headline-lg font-headline-lg text-on-surface">
          Physicians &amp; Specialists
          <span className="rounded-full bg-surface-container-high px-2 py-0.5 text-label-md font-label-md font-medium text-on-surface-variant">
            {activeCount} Active
          </span>
        </h1>
        <p className="mt-0.5 text-body-sm font-body-sm text-on-surface-variant">
          {facility.fullName} • ቅዱስ ጳውሎስ ሆስፒታል ሚሌኒየም ሜዲካል ኮሌጅ
        </p>
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() =>
            showToast("Filter panel focused: Select Department or Rank")
          }
          className="flex items-center gap-2 rounded-full bg-surface-container-lowest px-4 py-2.5 text-label-md font-label-md text-on-surface shadow-sm transition-all hover:bg-surface-container"
        >
          <Icon name="tune" className="text-[18px] text-outline" />
          <span>Filter View</span>
        </button>
        <button
          type="button"
          onClick={() =>
            showToast("Initiating New Physician Registration Wizard")
          }
          className="flex items-center gap-2 rounded-full bg-primary-container px-5 py-2.5 text-label-md font-label-md text-on-primary shadow-sm transition-all hover:bg-primary"
        >
          <Icon name="person_add" className="text-[20px]" />
          <span>
            + Add Doctor{" "}
            <span className="font-normal opacity-90">(አዲስ ሐኪም መዝግብ)</span>
          </span>
        </button>
      </div>
    </header>
  );
}
