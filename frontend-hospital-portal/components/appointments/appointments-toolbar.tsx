"use client";

import { forwardRef } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import {
  appointmentDepartments,
  appointmentVisitTypes,
} from "@/lib/appointments-list";

type ToolbarStatus = {
  key: string;
  label: string;
  count: number;
};

const TOOLBAR_STATUSES: ToolbarStatus[] = [
  { key: "all", label: "All", count: 145 },
  { key: "checked-in", label: "Checked In", count: 42 },
  { key: "in-consultation", label: "In Consultation", count: 28 },
  { key: "completed", label: "Completed", count: 65 },
  { key: "pending", label: "Pending / Requested", count: 10 },
];

type AppointmentsToolbarProps = {
  query: string;
  onQueryChange: (value: string) => void;
  department: string;
  onDepartmentChange: (value: string) => void;
  visitType: string;
  onVisitTypeChange: (value: string) => void;
  status: string;
  onStatusChange: (key: string) => void;
};

export const AppointmentsToolbar = forwardRef<HTMLInputElement, AppointmentsToolbarProps>(
  function AppointmentsToolbar(
    {
      query,
      onQueryChange,
      department,
      onDepartmentChange,
      visitType,
      onVisitTypeChange,
      status,
      onStatusChange,
    },
    ref
  ) {
    return (
      <div className="flex flex-col gap-space-md rounded-2xl bg-surface-container-lowest p-space-md shadow-soft mb-space-lg">
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-space-md">
          {/* Universal Quick Search */}
          <div className="relative flex-1 min-w-0">
            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-outline">
              <Icon name="search" className="text-[18px]" />
            </div>
            <input
              ref={ref}
              type="text"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Search by patient name, MRN, appointment ID, doctor..."
              className="w-full pl-10 pr-16 py-2.5 bg-surface-container-low rounded-xl font-body-md text-body-md text-on-surface placeholder:text-outline focus:outline-none focus:bg-surface-container-lowest focus:ring-2 focus:ring-primary-container transition-all"
            />
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
              <span className="font-label-sm text-label-sm px-1.5 py-0.5 rounded bg-surface-container text-outline">
                ⌘ K
              </span>
            </div>
          </div>

          {/* Department & Visit Type Selectors */}
          <div className="flex items-center gap-space-sm shrink-0">
            <DepartmentSelect
              value={department}
              onChange={onDepartmentChange}
              options={appointmentDepartments}
            />
            <DepartmentSelect
              value={visitType}
              onChange={onVisitTypeChange}
              options={appointmentVisitTypes}
            />
          </div>
        </div>

        {/* Status Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5 pt-1">
          {TOOLBAR_STATUSES.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => onStatusChange(s.key)}
              className={cn(
                "px-3.5 py-1.5 rounded-full font-label-md text-label-md shrink-0 transition-all",
                status === s.key
                  ? "bg-primary-container text-on-primary shadow-xs"
                  : "bg-surface-container-low text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
              )}
            >
              {s.label} <span className="ml-1 font-normal opacity-80">{s.count}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }
);

function DepartmentSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="appearance-none rounded-xl bg-surface-container-low pl-3 pr-8 py-2.5 cursor-pointer font-label-md text-label-md text-on-surface focus:outline-none"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <Icon
        name="expand_more"
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[16px] text-outline"
      />
    </div>
  );
}

export { TOOLBAR_STATUSES };
