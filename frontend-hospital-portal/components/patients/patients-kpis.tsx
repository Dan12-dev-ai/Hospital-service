"use client";

import { Icon } from "@/components/ui/icon";

type PatientKpi = {
  label: string;
  value: string;
  icon: string;
  iconClassName: string;
};

const patientKpis: PatientKpi[] = [
  {
    label: "Total Registered",
    value: "24,850",
    icon: "group",
    iconClassName: "bg-surface-container-low text-primary",
  },
  {
    label: "Admitted / In-Patients",
    value: "418",
    icon: "hotel",
    iconClassName: "bg-surface-container-low text-primary",
  },
  {
    label: "Outpatient Today",
    value: "312",
    icon: "clinical_notes",
    iconClassName: "bg-surface-container-low text-secondary",
  },
  {
    label: "Pending Triage / Intake",
    value: "19",
    icon: "medical_services",
    iconClassName: "bg-error-container/60 text-error",
  },
];

export function PatientsKpis() {
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {patientKpis.map((kpi) => (
        <div
          key={kpi.label}
          className="flex flex-col justify-between rounded-3xl bg-surface-container-lowest p-5 shadow-soft transition-all hover:shadow-md"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-xl ${kpi.iconClassName}`}
              >
                <Icon name={kpi.icon} className="text-[18px]" />
              </div>
              <span className="text-label-md font-label-md text-on-surface-variant">
                {kpi.label}
              </span>
            </div>
            <button
              type="button"
              aria-label={`More options for ${kpi.label}`}
              className="text-outline transition-colors hover:text-on-surface"
            >
              <Icon name="more_horiz" className="text-[18px]" />
            </button>
          </div>
          <div className="mt-4 flex items-baseline justify-between">
            <span className="text-metric-display font-metric-display tracking-tight text-on-surface">
              {kpi.value}
            </span>
          </div>
        </div>
      ))}
    </section>
  );
}
