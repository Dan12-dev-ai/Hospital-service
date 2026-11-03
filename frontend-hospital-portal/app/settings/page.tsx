import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { SettingsPage } from "@/components/settings/settings-page";

export const metadata: Metadata = {
  title: "Settings • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <SettingsPage />
    </DashboardShell>
  );
}
