"use client";

import { useState } from "react";
import { Icon } from "@/components/ui/icon";
import {
  ChartLegend,
  PeriodToggle,
  type Period,
} from "@/components/dashboard/chart-parts";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Daily patient volumes. Heights are in px (outpatient, in-patient),
 * mirroring the template's static bar chart.
 */
const WEEKLY_VOLUMES: { day: string; outpatient: number; inPatient: number }[] =
  [
    { day: "Sun", outpatient: 48, inPatient: 72 },
    { day: "Mon", outpatient: 64, inPatient: 112 },
    { day: "Tue", outpatient: 80, inPatient: 96 },
    { day: "Wed", outpatient: 88, inPatient: 104 },
    { day: "Thu", outpatient: 56, inPatient: 80 },
    { day: "Fri", outpatient: 64, inPatient: 72 },
    { day: "Sat", outpatient: 48, inPatient: 112 },
  ];

export function PatientOverviewChart() {
  const [period, setPeriod] = useState<Period>("Week");

  return (
    <div className="flex flex-col justify-between rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex cursor-pointer items-center gap-1.5">
          <span className="text-sm font-bold text-slate-800">
            Patient Overview
          </span>
          <Icon name="expand_more" className="text-[16px] text-slate-500" />
        </div>
        <PeriodToggle value={period} onChange={setPeriod} />
      </div>

      <ChartLegend
        items={[
          { colorClass: "bg-black", label: "In-Patient" },
          { colorClass: "bg-[#e5e7eb]", label: "Outpatient / Clinic" },
        ]}
      />

      {/* Dual Bar graph */}
      <div className="flex h-44 w-full flex-col justify-end">
        <div className="flex h-32 w-full items-end justify-between gap-2 border-b border-slate-100 px-2 pb-2">
          {WEEKLY_VOLUMES.map((entry) => (
            <div key={entry.day} className="flex items-end gap-1">
              <div
                className="w-2.5 rounded-t-sm bg-[#e5e7eb]"
                style={{ height: entry.outpatient }}
              />
              <div
                className="w-2.5 rounded-t-sm bg-black"
                style={{ height: entry.inPatient }}
              />
            </div>
          ))}
        </div>
        {/* Day labels */}
        <div className="flex w-full justify-between px-1 pt-2 text-[10px] font-medium text-slate-400">
          {DAYS.map((day) => (
            <span key={day}>{day}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
