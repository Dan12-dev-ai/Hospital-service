import { DashboardProvider } from "@/components/dashboard/dashboard-context";
import { Sidebar } from "@/components/dashboard/sidebar";
import { TopBar } from "@/components/dashboard/top-bar";
import { AlertBanner } from "@/components/dashboard/alert-banner";
import { PageHeader } from "@/components/dashboard/page-header";
import { KpiGrid } from "@/components/dashboard/kpi-grid";
import { RevenueChart } from "@/components/dashboard/revenue-chart";
import { PatientOverviewChart } from "@/components/dashboard/patient-overview-chart";
import { AppointmentsCard } from "@/components/dashboard/appointments-card";
import { AlertsCard } from "@/components/dashboard/alerts-card";
import { MiniCalendar } from "@/components/dashboard/mini-calendar";
import { AgendaTimeline } from "@/components/dashboard/agenda-timeline";

export default function DashboardPage() {
  return (
    <DashboardProvider>
      <div className="flex min-h-screen flex-col gap-5 p-4 lg:p-6 xl:flex-row">
        {/* Left Sidebar (Rounded floating template card) */}
        <Sidebar />

        {/* Main Content Area */}
        <main className="flex min-w-0 flex-1 flex-col gap-5">
          {/* Top Floating Header Bar */}
          <TopBar />

          {/* Operational Banner / Live Intake Toast */}
          <AlertBanner />

          {/* Dashboard Header Title & Action Buttons */}
          <PageHeader />

          {/* 4 KPI Metrics Row */}
          <KpiGrid />

          {/* Middle Section: Charts + Appointments + Alerts */}
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            {/* Left 2 Cols: Charts + Appointments + Alerts */}
            <div className="flex flex-col gap-5 xl:col-span-2">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <RevenueChart />
                <PatientOverviewChart />
              </div>
              <AppointmentsCard />
              <AlertsCard />
            </div>

            {/* Right Column: Calendar + Agenda Timeline */}
            <div className="flex flex-col gap-5">
              <MiniCalendar />
              <AgendaTimeline />
            </div>
          </div>
        </main>
      </div>
    </DashboardProvider>
  );
}
