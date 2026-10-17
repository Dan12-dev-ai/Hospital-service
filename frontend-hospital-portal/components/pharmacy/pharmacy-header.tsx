"use client";

import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { facility } from "@/lib/dashboard-data";

export function PharmacyHeader() {
  const { showToast } = useDashboard();

  return (
    <header className="flex flex-col justify-between gap-4 rounded-3xl bg-surface-container-lowest p-6 shadow-soft lg:flex-row lg:items-center">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-primary-fixed/40 px-2 py-0.5 text-label-sm font-label-sm font-bold uppercase tracking-wider text-primary">
            Central Pharmacy &amp; Dispensary • Outpatient &amp; Inpatient Rx
          </span>
          <span className="text-outline-variant">•</span>
          <span className="flex items-center gap-1 text-label-sm font-label-sm text-outline">
            <Icon name="local_pharmacy" className="text-[14px]" />
            ቅዱስ ጳውሎስ ሚሌኒየም ሜዲካል ኮሌጅ
          </span>
        </div>
        <h1 className="text-headline-lg font-headline-lg font-bold tracking-tight text-on-surface">
          Pharmacy Directory{" "}
          <span className="text-headline-md font-normal text-outline">
            — 218 Prescriptions Today
          </span>
        </h1>
        <p className="flex items-center gap-1.5 text-body-sm font-body-sm text-on-surface-variant">
          <Icon name="location_on" className="text-[16px] text-primary" />
          {facility.fullName} • Central Outpatient Pharmacy &amp; Satellite
          Inpatient Dispensary
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          onClick={() => showToast("Filter panel focused: Dispensary & Category")}
          className="flex items-center gap-2 rounded-xl bg-surface-container-low px-4 py-2.5 text-label-lg font-label-lg text-on-surface transition-all hover:bg-surface-container"
        >
          <Icon name="tune" className="text-[18px] text-outline" />
          <span>Filter View</span>
        </button>
        <button
          type="button"
          onClick={() => showToast("Opening new medication dispensation workflow")}
          className="group flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-label-lg font-label-lg text-on-primary shadow-sm transition-all hover:bg-primary-container"
        >
          <Icon
            name="add"
            className="text-[20px] transition-transform duration-300 group-hover:rotate-90"
          />
          <span>+ Dispense Medication (መድኃኒት ማደል)</span>
        </button>
      </div>
    </header>
  );
}
