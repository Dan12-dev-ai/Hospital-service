"use client";

import { cn } from "cn";

const PERIODS = ["Week", "Month", "Year"] as const;
export type Period = (typeof PERIODS)[number];

export function PeriodToggle({
  value,
  onChange,
}: {
  value: Period;
  onChange: (period: Period) => void;
}) {
  return (
    <div className="flex items-center rounded-full bg-slate-100 p-0.5 text-[11px]">
      {PERIODS.map((period) => (
        <button
          key={period}
          type="button"
          onClick={() => onChange(period)}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-medium transition-colors",
            value === period
              ? "bg-pine-green text-white"
              : "text-slate-500 hover:text-slate-800"
          )}
        >
          {period}
        </button>
      ))}
    </div>
  );
}

export function ChartLegend({
  items,
}: {
  items: { colorClass: string; label: string }[];
}) {
  return (
    <div className="mb-2 flex items-center gap-3 text-[11px] text-slate-500">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1">
          <span className={cn("h-2 w-2 rounded-full", item.colorClass)} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
