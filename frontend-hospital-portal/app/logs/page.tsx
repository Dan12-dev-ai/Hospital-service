import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { LogsPage } from "@/components/logs/logs-page";

export const metadata: Metadata = {
  title: "Logs • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <LogsPage />
    </DashboardShell>
  );
}
