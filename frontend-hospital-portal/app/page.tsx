import type { ReactNode } from "react";
import { PortalShell } from "@/components/dashboard/portal-shell";
import { AlertBanner } from "@/components/dashboard/alert-banner";
import { PageHeader } from "@/components/dashboard/page-header";
import { KpiGrid } from "@/components/dashboard/kpi-grid";
import { RevenueChart } from "@/components/dashboard/revenue-chart";
import { PatientOverviewChart } from "@/components/dashboard/patient-overview-chart";
import { AppointmentsCard } from "@/components/dashboard/appointments-card";
import { AlertsCard } from "@/components/dashboard/alerts-card";
import { MiniCalendar } from "@/components/dashboard/mini-calendar";
import { AgendaTimeline } from "@/components/dashboard/agenda-timeline";
import { SampleBadge } from "@/components/common/states";

/** A dashboard card whose content is illustrative (no backend for it yet). */
function Sample({ children }: { children: ReactNode }) {
  return (
    <div className="relative">
      <SampleBadge className="absolute -top-2 right-4 z-10 shadow-sm" />
      {children}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <PortalShell>
      {/* Video visits waiting for a doctor (real) */}
      <AlertBanner />

      <PageHeader />

      {/* Patients, bookings and doctors on duty are real; invoices are sample data. */}
      <KpiGrid />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="flex flex-col gap-5 xl:col-span-2">
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <Sample>
              <RevenueChart />
            </Sample>
            <Sample>
              <PatientOverviewChart />
            </Sample>
          </div>
          <Sample>
            <AppointmentsCard />
          </Sample>
          <Sample>
            <AlertsCard />
          </Sample>
        </div>

        <div className="flex flex-col gap-5">
          <Sample>
            <MiniCalendar />
          </Sample>
          <Sample>
            <AgendaTimeline />
          </Sample>
        </div>
      </div>
    </PortalShell>
  );
}
