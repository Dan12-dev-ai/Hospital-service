"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import {
  ChartLegend,
  PeriodToggle,
  type Period,
} from "@/components/dashboard/chart-parts";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function RevenueChart() {
  const [period, setPeriod] = useState<Period>("Week");

  return (
    <div className="flex flex-col justify-between rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex cursor-pointer items-center gap-1.5">
          <span className="text-sm font-bold text-slate-800">Revenue</span>
          <Icon name="expand_more" className="text-[16px] text-slate-500" />
        </div>
        <PeriodToggle value={period} onChange={setPeriod} />
      </div>

      <ChartLegend
        items={[
          { colorClass: "bg-pine-green", label: "Incomes" },
          { colorClass: "bg-[#34d399]", label: "Discharges" },
        ]}
      />

      {/* Wave SVG Line Graphic */}
      <div className="relative flex h-44 w-full items-center">
        <div className="absolute bottom-4 left-0 top-0 flex flex-col justify-between font-mono text-[10px] text-slate-300">
          <span>100k</span>
          <span>75k</span>
          <span>50k</span>
          <span>25k</span>
          <span>0</span>
        </div>
        <div className="flex h-full w-full flex-col justify-end pl-8">
          <svg
            className="h-32 w-full overflow-visible"
            viewBox="0 0 300 100"
            preserveAspectRatio="none"
            role="img"
            aria-label={`${period}ly revenue and discharge trends`}
          >
            {/* Grid lines */}
            <line x1="0" x2="300" y1="0" y2="0" stroke="#f1f5f9" strokeWidth="1" />
            <line x1="0" x2="300" y1="25" y2="25" stroke="#f1f5f9" strokeWidth="1" />
            <line x1="0" x2="300" y1="50" y2="50" stroke="#f1f5f9" strokeWidth="1" />
            <line x1="0" x2="300" y1="75" y2="75" stroke="#f1f5f9" strokeWidth="1" />
            {/* Curved wave 1 (Deep Pine) — Incomes */}
            <path
              d="M 0,55 C 30,55 45,45 75,55 C 105,65 120,20 150,20 C 180,20 195,60 225,35 C 255,15 270,45 300,42"
              fill="none"
              stroke="#1b6b57"
              strokeLinecap="round"
              strokeWidth="2.5"
            />
            {/* Curved wave 2 (Mint) — Discharges */}
            <path
              d="M 0,45 C 30,45 45,65 75,60 C 105,55 120,85 150,75 C 180,65 195,30 225,50 C 255,70 270,55 300,52"
              fill="none"
              stroke="#34d399"
              strokeLinecap="round"
              strokeWidth="2.5"
            />
          </svg>
          {/* Day labels */}
          <div className="flex w-full justify-between border-t border-slate-100 pt-2 text-[10px] font-medium text-slate-400">
            {DAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
