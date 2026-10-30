"use client";

import { Icon } from "@/components/ui/icon";
import type { PatientStats } from "@/lib/api-types";

type PatientKpi = {
  label: string;
  value: number | undefined;
  icon: string;
  iconClassName: string;
};

export function PatientsKpis({ stats }: { stats: PatientStats | null }) {
  const kpis: PatientKpi[] = [
    { label: "Total Registered", value: stats?.total, icon: "group", iconClassName: "bg-surface-container-low text-black" },
    {
      label: "Admitted / In-Patients",
      value: stats ? stats.by_status.admitted + stats.by_status.discharge : undefined,
      icon: "hotel",
      iconClassName: "bg-surface-container-low text-black",
    },
    { label: "Outpatients", value: stats?.by_status.opd, icon: "clinical_notes", iconClassName: "bg-surface-container-low text-neutral-600" },
    { label: "Emergency", value: stats?.by_status.emergency, icon: "medical_services", iconClassName: "bg-error-container/60 text-error" },
  ];
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {kpis.map((kpi) => (
        <div key={kpi.label} className="flex flex-col justify-between rounded-3xl bg-surface-container-lowest p-5 shadow-soft transition-all hover:shadow-md">
          <div className="flex items-center gap-2.5">
            <div className={`flex h-8 w-8 items-center justify-center rounded-xl ${kpi.iconClassName}`}>
              <Icon name={kpi.icon} className="text-[18px]" />
            </div>
            <span className="text-label-md font-label-md text-on-surface-variant">{kpi.label}</span>
          </div>
          <div className="mt-4 flex items-baseline justify-between">
            <span className="text-metric-display font-metric-display tracking-tight text-on-surface">
              {kpi.value?.toLocaleString("en-US") ?? "—"}
            </span>
            {kpi.label === "Total Registered" && stats && (
              <span className="text-label-sm font-label-sm text-outline">+{stats.registered_today} today</span>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
