"use client";

import { Icon } from "@/components/ui/icon";

type ReportsKpi = {
  label: string;
  value: string;
  badge: { text: string; className: string };
  footerIcon: string;
  footerIconClassName: string;
  footerText: string;
  icon: string;
};

const reportsKpis: ReportsKpi[] = [
  {
    label: "Total Generated",
    value: "1,248",
    badge: {
      text: "32 Automated",
      className: "bg-surface-container-high text-black",
    },
    footerIcon: "check",
    footerIconClassName: "text-black",
    footerText: "Across 14 medical departments",
    icon: "receipt_long",
  },
  {
    label: "Clinical Census Rate",
    value: "87.4%",
    badge: {
      text: "+2.3% MoM",
      className: "bg-neutral-600-container/50 text-neutral-800",
    },
    footerIcon: "trending_up",
    footerIconClassName: "text-neutral-600",
    footerText: "Above target IPD threshold",
    icon: "ward",
  },
  {
    label: "Avg OPD Turnaround",
    value: "24 min",
    badge: {
      text: "Triage to Rx",
      className: "bg-tertiary-fixed/30 text-tertiary",
    },
    footerIcon: "timer",
    footerIconClassName: "text-black",
    footerText: "-6 min versus last quarter",
    icon: "timelapse",
  },
  {
    label: "MoH Regulatory Sync",
    value: "100%",
    badge: {
      text: "MoH Validated",
      className: "bg-neutral-600-container/50 text-neutral-800",
    },
    footerIcon: "cloud_done",
    footerIconClassName: "text-neutral-600",
    footerText: "DHIS-2 payload dispatched",
    icon: "verified",
  },
];

export function ReportsKpis() {
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {reportsKpis.map((kpi) => (
        <div
          key={kpi.label}
          className="flex flex-col justify-between rounded-2xl bg-surface-container-lowest p-4 shadow-sm"
        >
          <div className="flex items-center justify-between text-outline">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-container-low text-black">
                <Icon name={kpi.icon} className="text-[18px]" />
              </div>
              <span className="font-body-md text-label-md text-on-surface-variant">
                {kpi.label}
              </span>
            </div>
            <button
              type="button"
              aria-label={`Options for ${kpi.label}`}
              className="rounded p-1 transition-colors hover:text-on-surface"
            >
              <Icon name="more_horiz" className="text-[18px]" />
            </button>
          </div>
          <div className="mt-3 flex items-baseline justify-between">
            <span className="font-metric-display text-metric-display font-bold tracking-tight text-on-surface">
              {kpi.value}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-label-sm font-label-sm font-semibold ${kpi.badge.className}`}
            >
              {kpi.badge.text}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-1 font-body-sm text-body-sm text-outline">
            <Icon
              name={kpi.footerIcon}
              className={`text-[14px] ${kpi.footerIconClassName}`}
            />
            <span>{kpi.footerText}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
