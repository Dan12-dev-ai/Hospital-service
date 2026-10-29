"use client";

import { cn } from "cn";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";


import {
  reportDepartments,
  reportFormats,
  reportPeriods,
  reportTabs,
} from "@/lib/reports-data";
import type { ReportTabKey } from "@/lib/report-types";

type ReportsToolbarProps = {
  tab: ReportTabKey;
  onTabChange: (tab: ReportTabKey) => void;
  period: string;
  onPeriodChange: (value: string) => void;
  department: string;
  onDepartmentChange: (value: string) => void;
  format: string;
  onFormatChange: (value: string) => void;
};

export function ReportsToolbar({
  tab,
  onTabChange,
  period,
  onPeriodChange,
  department,
  onDepartmentChange,
  format,
  onFormatChange,
}: ReportsToolbarProps) {
  return (
    <section className="flex flex-col justify-between gap-3 rounded-2xl bg-surface-container-lowest p-3 shadow-sm lg:flex-row lg:items-center">
      <div className="custom-scrollbar flex items-center gap-1.5 overflow-x-auto pb-1 lg:pb-0">
        {reportTabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onTabChange(item.key)}
            className={cn(
              "whitespace-nowrap rounded-xl px-3.5 py-2 font-label-lg text-label-sm transition-colors",
              tab === item.key
                ? "bg-black text-white shadow-sm"
                : "text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface"
            )}
          >
            {item.label} ({item.count.toLocaleString()})
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <SelectPill
          value={period}
          onChange={onPeriodChange}
          options={reportPeriods}
          ariaLabel="Filter by period"
        />
        <SelectPill
          value={department}
          onChange={onDepartmentChange}
          options={reportDepartments}
          ariaLabel="Filter by department"
        />
        <SelectPill
          value={format}
          onChange={onFormatChange}
          options={reportFormats}
          ariaLabel="Filter by export format"
        />
      </div>
    </section>
  );
}

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
    <Select value={value} onValueChange={(v) => onChange(v ?? value)}>
      <SelectTrigger aria-label={ariaLabel} className="cursor-pointer rounded-xl bg-surface-container-low py-1.5 pl-3 pr-8 font-label-md text-label-sm text-on-surface-variant focus:outline-none focus:ring-2 focus:ring-black/20">
        <SelectValue>{(v) => options.find((o) => o.value === v)?.label ?? v}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
