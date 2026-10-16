import type { ReactNode } from "react";
import { DashboardProvider } from "@/components/dashboard/dashboard-context";
import { Sidebar } from "@/components/dashboard/sidebar";
import { TopBar } from "@/components/dashboard/top-bar";

/**
 * Shared two-column shell (sidebar + optional top bar) for the portal's
 * secondary pages, mirroring the dashboard layout.
 *
 * Pass `showTopBar={false}` for pages that render their own page header
 * (e.g. the Doctors directory).
 */
export function PortalShell({
  children,
  showTopBar = true,
}: {
  children: ReactNode;
  showTopBar?: boolean;
}) {
  return (
    <DashboardProvider>
      <div className="flex min-h-screen flex-col gap-5 p-4 lg:p-6 xl:flex-row">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col gap-5">
          {showTopBar && <TopBar />}
          {children}
        </main>
      </div>
    </DashboardProvider>
  );
}

/** Simple "module coming soon" card used by the placeholder routes. */
export function PlaceholderPage({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl border border-card-border/80 bg-white p-16 text-center shadow-soft">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-pine-light text-pine-green">
        <span
          aria-hidden="true"
          className="material-symbols-outlined select-none text-[28px]"
        >
          {icon}
        </span>
      </div>
      <h1 className="text-xl font-bold tracking-tight text-slate-900">
        {title}
      </h1>
      <p className="mt-1 max-w-md text-xs text-slate-500">{description}</p>
      <span className="mt-4 rounded-full bg-mint-subtle px-3 py-1 text-[11px] font-semibold text-pine-green">
        Module coming soon
      </span>
    </div>
  );
}
