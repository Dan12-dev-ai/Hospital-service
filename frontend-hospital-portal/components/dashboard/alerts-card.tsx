import { Info } from "lucide-react";

import { hospitalAlerts } from "@/lib/dashboard-data";

export function AlertsCard() {
  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-800">
            Alerts &amp; Notifications
          </h2>
          <span className="text-[11px] text-slate-400">
            Important hospital operational updates
          </span>
        </div>
        <Info className="text-[18px] text-slate-400" />
      </div>

      {/* Alert pills */}
      <div className="space-y-2">
        {hospitalAlerts.map((alert) => (
          <div
            key={alert.id}
            className="flex items-center gap-2.5 rounded-2xl border border-neutral-100 bg-neutral-50/70 p-3 text-xs text-neutral-800"
          >
            <Info className="text-[17px] text-black" />
            <span className="font-medium">{alert.message}</span>
          </div>
        ))}
      </div>

      {/* Bed Occupancy & Staff on Duty Metrics */}
      <div className="grid grid-cols-1 gap-4 border-t border-slate-100 pt-2 sm:grid-cols-2">
        <div className="flex items-center justify-between rounded-2xl border border-slate-100 bg-slate-50 p-3">
          <div>
            <span className="block text-xs font-bold text-slate-800">
              Bed Occupancy
            </span>
            <span className="text-[10px] text-slate-400">
              248/300 beds occupied
            </span>
          </div>
          <span className="text-lg font-extrabold text-black">83%</span>
        </div>
        <div className="flex items-center justify-between rounded-2xl border border-slate-100 bg-slate-50 p-3">
          <div>
            <span className="block text-xs font-bold text-slate-800">
              Staff on Duty
            </span>
            <span className="text-[10px] text-slate-400">
              Today&apos;s active shift
            </span>
          </div>
          <span className="text-lg font-extrabold text-slate-800">165</span>
        </div>
      </div>
    </div>
  );
}
