"use client";

import { forwardRef } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";
import { patientTabs } from "@/lib/patients-data";
import type { PatientTabKey } from "@/lib/patient-types";

type PatientsToolbarProps = {
  query: string;
  onQueryChange: (value: string) => void;
  tab: PatientTabKey;
  onTabChange: (tab: PatientTabKey) => void;
  department: string;
  onDepartmentChange: (value: string) => void;
  ward: string;
  onWardChange: (value: string) => void;
  denseView: boolean;
  onDenseViewToggle: () => void;
  departments: string[];
  wards: string[];
};

export const PatientsToolbar = forwardRef<
  HTMLInputElement,
  PatientsToolbarProps
>(function PatientsToolbar(
  {
    query,
    onQueryChange,
    tab,
    onTabChange,
    department,
    onDepartmentChange,
    ward,
    onWardChange,
    denseView,
    onDenseViewToggle,
    departments,
    wards,
  },
  ref
) {
  const { showToast } = useDashboard();

  return (
    <div className="flex flex-col gap-3.5 rounded-3xl bg-surface-container-lowest p-4 shadow-soft">
      <div className="relative flex items-center">
        <Icon
          name="search"
          className="pointer-events-none absolute left-4 text-[20px] text-outline"
        />
        <input
          ref={ref}
          type="text"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search by patient name, MRN, Digital Health ID (DE ID), phone..."
          className="w-full rounded-2xl bg-surface-container-low/70 py-3 pl-11 pr-24 font-body-md text-body-md text-on-surface placeholder:text-outline transition-colors focus:bg-surface-container-low focus:outline-none"
        />
        <div className="pointer-events-none absolute right-3 flex select-none items-center gap-1 rounded-xl bg-surface-container px-2 py-1 text-label-sm font-label-sm text-outline">
          <span className="text-[10px]">⌘</span>
          <span>K</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
        <div className="custom-scrollbar inline-flex max-w-full gap-1 overflow-x-auto rounded-2xl bg-surface-container-low/80 p-1">
          {patientTabs.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onTabChange(item.key)}
              className={cn(
                "whitespace-nowrap rounded-xl px-3.5 py-1.5 text-label-sm font-label-sm transition-all",
                tab === item.key
                  ? "bg-primary text-on-primary"
                  : "text-on-surface-variant hover:text-on-surface"
              )}
            >
              {item.label}
              {item.count && <span> ({item.count})</span>}
            </button>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <SelectPill
            value={department}
            onChange={onDepartmentChange}
            options={departments}
            ariaLabel="Filter by department"
          />
          <SelectPill
            value={ward}
            onChange={onWardChange}
            options={wards}
            ariaLabel="Filter by ward"
          />
          <button
            type="button"
            title={denseView ? "Displaying condensed census view" : "Toggle dense view"}
            aria-label="Toggle dense view"
            onClick={() => {
              onDenseViewToggle();
              showToast(
                denseView
                  ? "Displaying standard census view"
                  : "Displaying condensed census view"
              );
            }}
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container"
          >
            <Icon name="view_agenda" className="text-[18px]" />
          </button>
        </div>
      </div>
    </div>
  );
});

function SelectPill({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  ariaLabel: string;
}) {
  return (
    <div className="relative">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="cursor-pointer appearance-none rounded-xl bg-surface-container-low px-3 py-1.5 text-label-sm font-label-sm text-on-surface focus:outline-none"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <Icon
        name="expand_more"
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[16px] text-outline"
      />
    </div>
  );
}
