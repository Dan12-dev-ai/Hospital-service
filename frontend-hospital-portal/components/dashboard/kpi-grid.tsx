import { KpiCard } from "@/components/dashboard/kpi-card";
import { kpiMetrics } from "@/lib/dashboard-data";

export function KpiGrid() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {kpiMetrics.map((metric) => (
        <KpiCard key={metric.label} metric={metric} />
      ))}
    </div>
  );
}
