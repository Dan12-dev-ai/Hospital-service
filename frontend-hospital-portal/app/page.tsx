import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { OverviewPage } from "@/components/overview/overview-page";

export const metadata: Metadata = {
  title: "Overview • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <OverviewPage />
    </DashboardShell>
  );
}
