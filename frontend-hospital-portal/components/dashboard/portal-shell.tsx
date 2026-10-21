import type { ReactNode } from "react";
import { DashboardProvider } from "@/components/dashboard/dashboard-context";
import { Sidebar } from "@/components/dashboard/sidebar";
import { TopBar } from "@/components/dashboard/top-bar";
import { SessionProvider } from "@/components/session/session-context";
import { HospitalStatusBanner } from "@/components/session/hospital-status-banner";
import { SidebarMobileProvider } from "@/components/dashboard/sidebar-mobile-context";

/**
 * Shared two-column shell (sidebar + optional top bar) for every portal
 * page. It loads the signed-in staff member and their hospital, and shows
 * the hospital's onboarding status (pending approval, suspended, unlisted).
 */
export function PortalShell({
  children,
  showTopBar = true,
}: {
  children: ReactNode;
  showTopBar?: boolean;
}) {
  return (
    <SessionProvider>
      <DashboardProvider>
        <SidebarMobileProvider>
          <div className="flex min-h-screen flex-col gap-5 p-4 lg:p-6 xl:flex-row">
            <Sidebar />
            <main className="flex min-w-0 flex-1 flex-col gap-5">
              {showTopBar && <TopBar />}
              <HospitalStatusBanner />
              {children}
            </main>
          </div>
        </SidebarMobileProvider>
      </DashboardProvider>
    </SessionProvider>
  );
}
