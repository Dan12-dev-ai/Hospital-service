import type { Metadata } from "next";
import { DashboardShell } from "@/components/shell/dashboard-shell";
import { TeamPage } from "@/components/team/team-page";

export const metadata: Metadata = {
  title: "Team • Endod Developers",
};

export default function Page() {
  return (
    <DashboardShell>
      <TeamPage />
    </DashboardShell>
  );
}
