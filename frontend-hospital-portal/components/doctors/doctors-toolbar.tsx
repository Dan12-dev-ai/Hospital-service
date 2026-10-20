"use client";

import { forwardRef } from "react";
import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import type { Department, DoctorList } from "@/lib/api-types";
import { RANK_OPTIONS, type DoctorStatusFilter } from "@/lib/doctor-types";

const STATUS_FILTERS: { key: DoctorStatusFilter; label: string }[] = [
  { key: "all", label: "All Doctors" },
  { key: "on-duty", label: "On Duty" },
  { key: "in-consultation", label: "In Consultation" },
  { key: "on-call", label: "On-Call / Surgery" },
  { key: "off-duty", label: "Off Duty" },
];

type DoctorsToolbarProps = {
  query: string;
  onQueryChange: (value: string) => void;
  department: string;
  onDepartmentChange: (value: string) => void;
  departments: Department[];
  rank: string;
  onRankChange: (value: string) => void;
  status: DoctorStatusFilter;
  onStatusChange: (status: DoctorStatusFilter) => void;
  /** Per-status counts from the API (they follow every filter except the status). */
  counts: DoctorList["counts"] | null;
};

export const DoctorsToolbar = forwardRef<HTMLInputElement, DoctorsToolbarProps>(
  function DoctorsToolbar(
    {
      query,
      onQueryChange,
      department,
      onDepartmentChange,
      departments,
      rank,
      onRankChange,
      status,
      onStatusChange,
      counts,
    },
    ref
  ) {
    return (
      <section className="mb-6 space-y-3 rounded-2xl bg-surface-container-lowest p-4 shadow-sm">
        <div className="flex flex-col items-center gap-3 lg:flex-row">
          {/* Universal Search Input */}
          <div className="relative w-full lg:flex-1">
            <Icon
              name="search"
              className="absolute left-4 top-1/2 -translate-y-1/2 text-[20px] text-outline"
            />
            <input
              ref={ref}
              type="text"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Search by doctor name, license ID, department, specialty, phone..."
              className="w-full rounded-full border-none bg-surface-container-low py-2.5 pl-11 pr-14 text-body-md font-body-md text-on-surface placeholder:text-outline focus:outline-none focus:ring-2 focus:ring-primary-container"
            />
            <div className="absolute right-3.5 top-1/2 flex -translate-y-1/2 items-center gap-1 rounded bg-surface-container-high px-1.5 py-0.5 text-label-sm font-label-sm text-on-surface-variant">
              <span>⌘</span>
              <span>K</span>
            </div>
          </div>

          {/* Dropdown Select Pills */}
          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
            <SelectPill
              value={department}
              onChange={onDepartmentChange}
              options={[
                { value: "all", label: "All Departments" },
                ...departments.map((d) => ({ value: d.id, label: d.name })),
              ]}
              ariaLabel="Filter by department"
            />
            <SelectPill
              value={rank}
              onChange={onRankChange}
              options={[{ value: "all", label: "All Ranks" }, ...RANK_OPTIONS]}
              ariaLabel="Filter by rank"
            />
          </div>
        </div>

        {/* Status Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={() => onStatusChange(filter.key)}
              className={cn(
                "rounded-full px-3.5 py-1.5 text-label-md font-label-md transition-all",
                status === filter.key
                  ? "bg-primary-container text-on-primary"
                  : "text-on-surface-variant hover:bg-surface-container"
              )}
            >
              {filter.label}
              {counts ? ` (${filter.key === "all" ? counts.all : counts[filter.key]})` : ""}
            </button>
          ))}
        </div>
      </section>
    );
  }
);

function SelectPill({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  ariaLabel: string;
}) {
  return (
    <div className="relative">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="cursor-pointer appearance-none rounded-full border-none bg-surface-container-low py-2 pl-3.5 pr-8 text-label-md font-label-md text-on-surface focus:ring-2 focus:ring-primary-container"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Icon
        name="expand_more"
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[18px] text-outline"
      />
    </div>
  );
}
