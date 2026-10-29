import type { ComponentType } from "react";
import { Badge, Calendar, Receipt, TrendingUp, Users } from "lucide-react";
import { SampleBadge } from "@/components/common/states";
import type { KpiMetric } from "@/lib/dashboard-types";

const KPI_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  groups: Users,
  calendar_today: Calendar,
  receipt: Receipt,
  badge: Badge,
};

export function KpiCard({ metric }: { metric: KpiMetric }) {
  return (
    <div data-testid="kpi-card" data-label={metric.label} className="flex flex-col justify-between rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-700">
            {(() => {
              const IconComp = KPI_ICONS[metric.icon];
              return IconComp ? <IconComp className="text-[18px]" /> : null;
            })()}
          </div>
          <span>{metric.label}</span>
        </div>
        {metric.sample && <SampleBadge />}
      </div>
      <div className="mt-4">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-extrabold tracking-tight text-slate-800">
            {metric.value}
          </span>
          {metric.trend && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-neutral-50 px-2 py-0.5 text-[11px] font-semibold text-neutral-700">
              <TrendingUp className="text-[14px]" />
              {metric.trend}
            </span>
          )}
        </div>
        <span className="mt-1 block text-[11px] font-normal text-slate-400">
          {metric.caption}
        </span>
      </div>
    </div>
  );
}
