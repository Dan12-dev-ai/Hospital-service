import { Icon } from "@/components/ui/icon";
import type { DoctorList } from "@/lib/api-types";

type DoctorKpi = {
  label: string;
  icon: string;
  value: number | undefined;
  iconBgClass: string;
  iconTextClass: string;
};

export function DoctorsKpis({ counts }: { counts: DoctorList["counts"] | null }) {
  const kpis: DoctorKpi[] = [
    { label: "Total Doctors", icon: "stethoscope", value: counts?.all, iconBgClass: "bg-surface-container-high", iconTextClass: "text-primary" },
    { label: "On Duty", icon: "pulse_alert", value: counts?.["on-duty"], iconBgClass: "bg-secondary-fixed/40", iconTextClass: "text-secondary" },
    { label: "In Consultation", icon: "schedule", value: counts?.["in-consultation"], iconBgClass: "bg-surface-variant", iconTextClass: "text-tertiary" },
    { label: "On-Call / Surgery", icon: "medical_services", value: counts?.["on-call"], iconBgClass: "bg-tertiary-fixed/30", iconTextClass: "text-tertiary-container" },
  ];
  return (
    <section className="grid grid-cols-1 gap-4 py-6 sm:grid-cols-2 lg:grid-cols-4">
      {kpis.map((kpi) => (
        <div key={kpi.label} className="flex flex-col justify-between rounded-2xl bg-surface-container-lowest p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2.5">
            <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${kpi.iconBgClass} ${kpi.iconTextClass}`}>
              <Icon name={kpi.icon} className="text-[20px]" />
            </div>
            <span className="text-label-md font-label-md text-outline">{kpi.label}</span>
          </div>
          <div className="text-metric-display font-metric-display text-on-surface">{kpi.value ?? "—"}</div>
        </div>
      ))}
    </section>
  );
}
