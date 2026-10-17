"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { facility } from "@/lib/dashboard-data";

export function PatientsHeader({ onRegister }: { onRegister: () => void }) {
  const { showToast } = useDashboard();

  return (
    <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-2.5">
          <h1 className="text-headline-lg font-headline-lg tracking-tight text-on-surface">
            Patients
          </h1>
          <span className="inline-flex items-center rounded-full bg-surface-container-high px-2.5 py-0.5 text-label-sm font-label-sm text-primary">
            Active Census
          </span>
        </div>
        <p className="mt-0.5 truncate text-body-md font-body-md text-on-surface-variant">
          Patient directory, admissions &amp; active clinical census •{" "}
          {facility.fullName} (ቅዱስ ጳውሎስ ሆስፒታል)
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          onClick={() => showToast("Applying advanced filters...")}
          className="flex items-center gap-2 rounded-2xl bg-surface-container-lowest px-4 py-2.5 text-label-lg font-label-lg text-on-surface shadow-soft transition-all hover:bg-surface-container"
        >
          <Icon name="tune" className="text-[18px] text-on-surface-variant" />
          <span>Filter View</span>
        </button>
        <button
          type="button"
          onClick={onRegister}
          className="group flex items-center gap-2 rounded-2xl bg-primary px-4 py-2.5 text-label-lg font-label-lg text-on-primary shadow-glow transition-all hover:bg-surface-tint"
        >
          <Icon
            name="add"
            className="text-[20px] transition-transform group-hover:rotate-90"
          />
          <span>Register Patient (አዲስ ታካሚ)</span>
        </button>
      </div>
    </header>
  );
}
