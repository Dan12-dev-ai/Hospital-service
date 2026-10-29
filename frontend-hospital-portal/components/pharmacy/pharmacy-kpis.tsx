"use client";

import { Icon } from "@/components/ui/icon";

type PharmacyKpi = {
  label: string;
  value: string;
  valueClassName?: string;
  badge: { text: string; className: string };
  icon: string;
  iconBoxClassName: string;
};

const pharmacyKpis: PharmacyKpi[] = [
  {
    label: "Total Prescriptions",
    value: "218",
    badge: {
      text: "Daily Total",
      className: "bg-surface-container text-on-surface-variant",
    },
    icon: "prescriptions",
    iconBoxClassName: "bg-surface-container-low text-black",
  },
  {
    label: "Dispensed Today",
    value: "154",
    badge: {
      text: "ETB 428,900",
      className: "bg-neutral-200 text-neutral-800",
    },
    icon: "task_alt",
    iconBoxClassName: "bg-neutral-200/30 text-neutral-600",
  },
  {
    label: "Pending Dispensation",
    value: "52",
    badge: {
      text: "~14 min queue",
      className: "bg-tertiary-fixed-dim/30 text-on-tertiary-fixed-variant",
    },
    icon: "pending_actions",
    iconBoxClassName: "bg-tertiary-fixed/30 text-tertiary",
  },
  {
    label: "Out of Stock / Alert",
    value: "12",
    valueClassName: "text-error",
    badge: {
      text: "Reorder Reqd",
      className: "bg-error-container/60 text-on-error-container",
    },
    icon: "inventory_2",
    iconBoxClassName: "bg-error-container text-on-error-container",
  },
];

export function PharmacyKpis() {
  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {pharmacyKpis.map((kpi) => (
        <div
          key={kpi.label}
          className="flex flex-col justify-between rounded-2xl bg-surface-container-lowest p-5 shadow-sm transition-all hover:shadow-md"
        >
          <div className="flex items-center justify-between">
            <span className="font-label-md text-label-md font-medium uppercase tracking-wide text-outline">
              {kpi.label}
            </span>
            <div
              className={`flex h-9 w-9 items-center justify-center rounded-xl ${kpi.iconBoxClassName}`}
            >
              <Icon name={kpi.icon} className="text-[20px]" />
            </div>
          </div>
          <div className="mt-4 flex items-baseline justify-between">
            <div
              className={`font-metric-display text-metric-display font-bold tracking-tight ${kpi.valueClassName ?? "text-on-surface"}`}
            >
              {kpi.value}
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-label-sm font-label-sm font-semibold ${kpi.badge.className}`}
            >
              {kpi.badge.text}
            </span>
          </div>
        </div>
      ))}
    </section>
  );
}
