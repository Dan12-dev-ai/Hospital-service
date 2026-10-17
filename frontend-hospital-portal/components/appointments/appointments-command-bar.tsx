"use client";

import { cn } from "cn";
import { Icon } from "@/components/ui/icon";
import { useDashboard } from "@/components/dashboard/dashboard-context";

export function AppointmentsCommandBar() {
  const { showToast } = useDashboard();

  return (
    <div className="flex flex-col md:flex-row md:items-end justify-between gap-space-md mb-space-xl">
      <div className="flex flex-col min-w-0">
        <div className="flex items-center gap-space-xs mb-1">
          <span className="w-1.5 h-1.5 rounded-full bg-primary-container" />
          <span className="font-label-sm text-label-sm uppercase tracking-wider text-outline">
            Clinical Appointments • Schedule &amp; Visits
          </span>
        </div>
        <h1 className="font-headline-xl text-headline-xl leading-none text-on-surface mb-1 tracking-tight">
          Appointments Directory
          <span className="font-body-md font-normal text-headline-lg text-outline">
            — 145 Scheduled Today
          </span>
        </h1>
        <p className="font-body-sm text-body-sm text-outline flex items-center gap-1.5">
          <Icon name="local_hospital" className="text-[15px] text-primary" />
          <span>
            St. Paul&apos;s Millennium Medical Center • ቅዱስ ጳውሎስ ሆስፒታል ሚሌኒየም
            ሜዲካል ኮሌጅ
          </span>
        </p>
      </div>

      {/* Quick Action Controls */}
      <div className="flex items-center gap-space-sm shrink-0">
        <button
          type="button"
          onClick={() => showToast("Filter panel focused")}
          className="flex items-center gap-1.5 rounded-xl px-space-md py-2.5 bg-surface-container-lowest text-on-surface font-label-md text-label-md shadow-soft hover:bg-surface-container-high transition-all"
        >
          <Icon name="tune" className="text-[18px] text-outline" />
          <span>Filter View</span>
        </button>
        <button
          type="button"
          onClick={() =>
            showToast("Opening new appointment scheduling modal")
          }
          className="flex items-center gap-2 rounded-xl px-space-lg py-2.5 bg-primary-container text-on-primary font-label-md text-label-md shadow-md hover:bg-primary transition-all"
        >
          <Icon name="add" className="text-[18px]" />
          <span>
            New Appointment <span className="font-normal opacity-90">(አዲስ ቀጠሮ)</span>
          </span>
        </button>
      </div>
    </div>
  );
}

export const KpiQuads = [
  {
    label: "Total Today",
    value: "145",
    icon: "calendar_today",
    iconClass: "bg-surface-container text-primary",
  },
  {
    label: "Checked In / Waiting",
    value: "42",
    icon: "timer",
    iconClass: "bg-secondary-container text-on-secondary-container",
  },
  {
    label: "In Consultation",
    value: "28",
    icon: "stethoscope",
    iconClass: "bg-primary-fixed text-on-primary-fixed-variant",
  },
  {
    label: "Completed Today",
    value: "65",
    icon: "check_circle",
    iconClass: "bg-surface-container-high text-primary-container",
  },
];

export function AppointmentsKpis() {
  return (
    <div className="grid gap-space-md mb-space-xl grid-cols-2 lg:grid-cols-4">
      {KpiQuads.map((kpi) => (
        <div
          key={kpi.label}
          className="flex flex-col justify-between h-32 rounded-2xl bg-surface-container-lowest p-space-lg shadow-soft"
        >
          <div className="flex items-center justify-between">
            <span className="font-label-md text-label-md text-outline">
              {kpi.label}
            </span>
            <div className={cn(
              "flex items-center justify-center rounded-xl h-8 w-8 text-primary",
              kpi.iconClass,
            )}>
              <Icon name={kpi.icon} className="text-[18px]" />
            </div>
          </div>
          <div className="font-metric-display text-metric-display text-on-surface tracking-tight">
            {kpi.value}
          </div>
        </div>
      ))}
    </div>
  );
}
