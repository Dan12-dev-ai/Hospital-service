import { DashboardProvider } from "@/components/dashboard/dashboard-context";
import { Sidebar } from "@/components/dashboard/sidebar";
import { AppointmentsTopBar } from "@/components/appointments/appointments-top-bar";

/**
 * Appointments shell. Mirrors the dashboard / doctors PortalShell layout:
 * a flex row (side-by-side on large screens) with the shared dashboard
 * `<Sidebar>` and the appointments main content area, so the body sits to
 * the right of the left sidebar instead of stacking below it.
 */
export default function AppointmentsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardProvider>
      <div className="flex min-h-screen flex-col gap-5 p-4 lg:p-6 xl:flex-row">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col gap-5">
          <AppointmentsTopBar />
          <div className="flex flex-col w-full">{children}</div>
        </main>
      </div>
    </DashboardProvider>
  );
}
